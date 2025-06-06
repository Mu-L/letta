"""Key idea: create drop-in replacement for agent's ChatCompletion call that runs on an OpenLLM backend"""

import uuid

import requests

from letta.constants import CLI_WARNING_PREFIX
from letta.errors import LocalLLMConnectionError, LocalLLMError
from letta.helpers.datetime_helpers import get_utc_time_int
from letta.helpers.json_helpers import json_dumps
from letta.local_llm.constants import DEFAULT_WRAPPER
from letta.local_llm.function_parser import patch_function
from letta.local_llm.grammars.gbnf_grammar_generator import create_dynamic_model_from_function, generate_gbnf_grammar_and_documentation
from letta.local_llm.koboldcpp.api import get_koboldcpp_completion
from letta.local_llm.llamacpp.api import get_llamacpp_completion
from letta.local_llm.llm_chat_completion_wrappers import simple_summary_wrapper
from letta.local_llm.lmstudio.api import get_lmstudio_completion, get_lmstudio_completion_chatcompletions
from letta.local_llm.ollama.api import get_ollama_completion
from letta.local_llm.utils import count_tokens, get_available_wrappers
from letta.local_llm.vllm.api import get_vllm_completion
from letta.local_llm.webui.api import get_webui_completion
from letta.local_llm.webui.legacy_api import get_webui_completion as get_webui_completion_legacy
from letta.otel.tracing import log_event
from letta.prompts.gpt_summarize import SYSTEM as SUMMARIZE_SYSTEM_MESSAGE
from letta.schemas.openai.chat_completion_response import ChatCompletionResponse, Choice, Message, ToolCall, UsageStatistics
from letta.utils import get_tool_call_id

has_shown_warning = False
grammar_supported_backends = ["koboldcpp", "llamacpp", "webui", "webui-legacy"]


def get_chat_completion(
    model,
    # no model required (except for Ollama), since the model is fixed to whatever you set in your own backend
    messages,
    functions=None,
    functions_python=None,
    function_call="auto",
    context_window=None,
    user=None,
    # required
    wrapper=None,
    endpoint=None,
    endpoint_type=None,
    # optional cleanup
    function_correction=True,
    # extra hints to allow for additional prompt formatting hacks
    # TODO this could alternatively be supported via passing function_call="send_message" into the wrapper
    first_message=False,
    # optional auth headers
    auth_type=None,
    auth_key=None,
) -> ChatCompletionResponse:
    from letta.utils import printd

    assert context_window is not None, "Local LLM calls need the context length to be explicitly set"
    assert endpoint is not None, "Local LLM calls need the endpoint (eg http://localendpoint:1234) to be explicitly set"
    assert endpoint_type is not None, "Local LLM calls need the endpoint type (eg webui) to be explicitly set"
    global has_shown_warning
    grammar = None

    # TODO: eventually just process Message object
    if not isinstance(messages[0], dict):
        messages = [m.to_openai_dict() for m in messages]

    if function_call is not None and function_call != "auto":
        raise ValueError(f"function_call == {function_call} not supported (auto or None only)")

    available_wrappers = get_available_wrappers()
    documentation = None

    # Special case for if the call we're making is coming from the summarizer
    if messages[0]["role"] == "system" and messages[0]["content"].strip() == SUMMARIZE_SYSTEM_MESSAGE.strip():
        llm_wrapper = simple_summary_wrapper.SimpleSummaryWrapper()

    # Select a default prompt formatter
    elif wrapper is None:
        # Warn the user that we're using the fallback
        if not has_shown_warning:
            print(f"{CLI_WARNING_PREFIX}no prompt formatter specified for local LLM, using the default formatter")
            has_shown_warning = True

        llm_wrapper = DEFAULT_WRAPPER()

    # User provided an incorrect prompt formatter
    elif wrapper not in available_wrappers:
        raise ValueError(f"Could not find requested wrapper '{wrapper} in available wrappers list:\n{', '.join(available_wrappers)}")

    # User provided a correct prompt formatter
    else:
        llm_wrapper = available_wrappers[wrapper]

    # If the wrapper uses grammar, generate the grammar using the grammar generating function
    # TODO move this to a flag
    if wrapper is not None and "grammar" in wrapper:
        # When using grammars, we don't want to do any extras output tricks like appending a response prefix
        setattr(llm_wrapper, "assistant_prefix_extra_first_message", "")
        setattr(llm_wrapper, "assistant_prefix_extra", "")

        # TODO find a better way to do this than string matching (eg an attribute)
        if "noforce" in wrapper:
            # "noforce" means that the prompt formatter expects inner thoughts as a top-level parameter
            # this is closer to the OpenAI style since it allows for messages w/o any function calls
            # however, with bad LLMs it makes it easier for the LLM to "forget" to call any of the functions
            grammar, documentation = generate_grammar_and_documentation(
                functions_python=functions_python,
                add_inner_thoughts_top_level=True,
                add_inner_thoughts_param_level=False,
                allow_only_inner_thoughts=True,
            )
        else:
            # otherwise, the other prompt formatters will insert inner thoughts as a function call parameter (by default)
            # this means that every response from the LLM will be required to call a function
            grammar, documentation = generate_grammar_and_documentation(
                functions_python=functions_python,
                add_inner_thoughts_top_level=False,
                add_inner_thoughts_param_level=True,
                allow_only_inner_thoughts=False,
            )
        printd(grammar)

    if grammar is not None and endpoint_type not in grammar_supported_backends:
        print(
            f"{CLI_WARNING_PREFIX}grammars are currently not supported when using {endpoint_type} as the Letta local LLM backend (supported: {', '.join(grammar_supported_backends)})"
        )
        grammar = None

    # First step: turn the message sequence into a prompt that the model expects
    try:
        # if hasattr(llm_wrapper, "supports_first_message"):
        if hasattr(llm_wrapper, "supports_first_message") and llm_wrapper.supports_first_message:
            prompt = llm_wrapper.chat_completion_to_prompt(
                messages=messages, functions=functions, first_message=first_message, function_documentation=documentation
            )
        else:
            prompt = llm_wrapper.chat_completion_to_prompt(messages=messages, functions=functions, function_documentation=documentation)

        printd(prompt)
    except Exception as e:
        print(e)
        raise LocalLLMError(
            f"Failed to convert ChatCompletion messages into prompt string with wrapper {str(llm_wrapper)} - error: {str(e)}"
        )

    # get the schema for the model

    """
    if functions_python is not None:
        model_schema = generate_schema(functions)
    else:
        model_schema = None
    """
    log_event(name="llm_request_sent", attributes={"prompt": prompt, "grammar": grammar})
    # Run the LLM
    try:
        result_reasoning = None
        if endpoint_type == "webui":
            result, usage = get_webui_completion(endpoint, auth_type, auth_key, prompt, context_window, grammar=grammar)
        elif endpoint_type == "webui-legacy":
            result, usage = get_webui_completion_legacy(endpoint, auth_type, auth_key, prompt, context_window, grammar=grammar)
        elif endpoint_type == "lmstudio-chatcompletions":
            result, usage, result_reasoning = get_lmstudio_completion_chatcompletions(endpoint, auth_type, auth_key, model, messages)
        elif endpoint_type == "lmstudio":
            result, usage = get_lmstudio_completion(endpoint, auth_type, auth_key, prompt, context_window, api="completions")
        elif endpoint_type == "lmstudio-legacy":
            result, usage = get_lmstudio_completion(endpoint, auth_type, auth_key, prompt, context_window, api="chat")
        elif endpoint_type == "llamacpp":
            result, usage = get_llamacpp_completion(endpoint, auth_type, auth_key, prompt, context_window, grammar=grammar)
        elif endpoint_type == "koboldcpp":
            result, usage = get_koboldcpp_completion(endpoint, auth_type, auth_key, prompt, context_window, grammar=grammar)
        elif endpoint_type == "ollama":
            result, usage = get_ollama_completion(endpoint, auth_type, auth_key, model, prompt, context_window)
        elif endpoint_type == "vllm":
            result, usage = get_vllm_completion(endpoint, auth_type, auth_key, model, prompt, context_window, user)
        else:
            raise LocalLLMError(
                f"Invalid endpoint type {endpoint_type}, please set variable depending on your backend (webui, lmstudio, llamacpp, koboldcpp)"
            )
    except requests.exceptions.ConnectionError as e:
        raise LocalLLMConnectionError(f"Unable to connect to endpoint {endpoint}")

    attributes = usage if isinstance(usage, dict) else {"usage": usage}
    attributes.update({"result": result})
    log_event(name="llm_request_sent", attributes=attributes)

    if result is None or result == "":
        raise LocalLLMError(f"Got back an empty response string from {endpoint}")
    printd(f"Raw LLM output:\n====\n{result}\n====")

    try:
        if hasattr(llm_wrapper, "supports_first_message") and llm_wrapper.supports_first_message:
            chat_completion_result = llm_wrapper.output_to_chat_completion_response(result, first_message=first_message)
        else:
            chat_completion_result = llm_wrapper.output_to_chat_completion_response(result)
        printd(json_dumps(chat_completion_result, indent=2))
    except Exception as e:
        raise LocalLLMError(f"Failed to parse JSON from local LLM response - error: {str(e)}")

    # Run through some manual function correction (optional)
    if function_correction:
        chat_completion_result = patch_function(message_history=messages, new_message=chat_completion_result)

    # Fill in potential missing usage information (used for tracking token use)
    if not ("prompt_tokens" in usage and "completion_tokens" in usage and "total_tokens" in usage):
        raise LocalLLMError(f"usage dict in response was missing fields ({usage})")

    if usage["prompt_tokens"] is None:
        printd(f"usage dict was missing prompt_tokens, computing on-the-fly...")
        usage["prompt_tokens"] = count_tokens(prompt)

    # NOTE: we should compute on-the-fly anyways since we might have to correct for errors during JSON parsing
    usage["completion_tokens"] = count_tokens(json_dumps(chat_completion_result))
    """
    if usage["completion_tokens"] is None:
        printd(f"usage dict was missing completion_tokens, computing on-the-fly...")
        # chat_completion_result is dict with 'role' and 'content'
        # token counter wants a string
        usage["completion_tokens"] = count_tokens(json_dumps(chat_completion_result))
    """

    # NOTE: this is the token count that matters most
    if usage["total_tokens"] is None:
        printd(f"usage dict was missing total_tokens, computing on-the-fly...")
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]

    # unpack with response.choices[0].message.content
    response = ChatCompletionResponse(
        id=str(uuid.uuid4()),  # TODO something better?
        choices=[
            Choice(
                finish_reason="stop",
                index=0,
                message=Message(
                    role=chat_completion_result["role"],
                    content=result_reasoning if result_reasoning is not None else chat_completion_result["content"],
                    tool_calls=(
                        [ToolCall(id=get_tool_call_id(), type="function", function=chat_completion_result["function_call"])]
                        if "function_call" in chat_completion_result
                        else []
                    ),
                ),
            )
        ],
        created=get_utc_time_int(),
        model=model,
        # "This fingerprint represents the backend configuration that the model runs with."
        # system_fingerprint=user if user is not None else "null",
        system_fingerprint=None,
        object="chat.completion",
        usage=UsageStatistics(**usage),
    )
    printd(response)
    return response


def generate_grammar_and_documentation(
    functions_python: dict,
    add_inner_thoughts_top_level: bool,
    add_inner_thoughts_param_level: bool,
    allow_only_inner_thoughts: bool,
):
    from letta.utils import printd

    assert not (
        add_inner_thoughts_top_level and add_inner_thoughts_param_level
    ), "Can only place inner thoughts in one location in the grammar generator"

    grammar_function_models = []
    # create_dynamic_model_from_function will add inner thoughts to the function parameters if add_inner_thoughts is True.
    # generate_gbnf_grammar_and_documentation will add inner thoughts to the outer object of the function parameters if add_inner_thoughts is True.
    for key, func in functions_python.items():
        grammar_function_models.append(create_dynamic_model_from_function(func, add_inner_thoughts=add_inner_thoughts_param_level))
    grammar, documentation = generate_gbnf_grammar_and_documentation(
        grammar_function_models,
        outer_object_name="function",
        outer_object_content="params",
        model_prefix="function",
        fields_prefix="params",
        add_inner_thoughts=add_inner_thoughts_top_level,
        allow_only_inner_thoughts=allow_only_inner_thoughts,
    )
    printd(grammar)
    return grammar, documentation
