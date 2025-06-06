from letta.log import get_logger

logger = get_logger(__name__)


# class BaseMCPClient:
#    def __init__(self, server_config: BaseServerConfig):
#        self.server_config = server_config
#        self.session: Optional[ClientSession] = None
#        self.stdio = None
#        self.write = None
#        self.initialized = False
#        self.loop = asyncio.new_event_loop()
#        self.cleanup_funcs = []
#
#    def connect_to_server(self):
#        asyncio.set_event_loop(self.loop)
#        success = self._initialize_connection(self.server_config, timeout=tool_settings.mcp_connect_to_server_timeout)
#
#        if success:
#            try:
#                self.loop.run_until_complete(
#                    asyncio.wait_for(self.session.initialize(), timeout=tool_settings.mcp_connect_to_server_timeout)
#                )
#                self.initialized = True
#            except asyncio.TimeoutError:
#                raise MCPTimeoutError("initializing session", self.server_config.server_name, tool_settings.mcp_connect_to_server_timeout)
#        else:
#            raise RuntimeError(
#                f"Connecting to MCP server failed. Please review your server config: {self.server_config.model_dump_json(indent=4)}"
#            )
#
#    def _initialize_connection(self, server_config: BaseServerConfig, timeout: float) -> bool:
#        raise NotImplementedError("Subclasses must implement _initialize_connection")
#
#    def list_tools(self) -> List[MCPTool]:
#        self._check_initialized()
#        try:
#            response = self.loop.run_until_complete(
#                asyncio.wait_for(self.session.list_tools(), timeout=tool_settings.mcp_list_tools_timeout)
#            )
#            return response.tools
#        except asyncio.TimeoutError:
#            logger.error(
#                f"Timed out while listing tools for MCP server {self.server_config.server_name} (timeout={tool_settings.mcp_list_tools_timeout}s)."
#            )
#            raise MCPTimeoutError("listing tools", self.server_config.server_name, tool_settings.mcp_list_tools_timeout)
#
#    def execute_tool(self, tool_name: str, tool_args: dict) -> Tuple[str, bool]:
#        self._check_initialized()
#        try:
#            result = self.loop.run_until_complete(
#                asyncio.wait_for(self.session.call_tool(tool_name, tool_args), timeout=tool_settings.mcp_execute_tool_timeout)
#            )
#
#            parsed_content = []
#            for content_piece in result.content:
#                if isinstance(content_piece, TextContent):
#                    parsed_content.append(content_piece.text)
#                    print("parsed_content (text)", parsed_content)
#                else:
#                    parsed_content.append(str(content_piece))
#                    print("parsed_content (other)", parsed_content)
#
#            if len(parsed_content) > 0:
#                final_content = " ".join(parsed_content)
#            else:
#                # TODO move hardcoding to constants
#                final_content = "Empty response from tool"
#
#            return final_content, result.isError
#        except asyncio.TimeoutError:
#            logger.error(
#                f"Timed out while executing tool '{tool_name}' for MCP server {self.server_config.server_name} (timeout={tool_settings.mcp_execute_tool_timeout}s)."
#            )
#            raise MCPTimeoutError(f"executing tool '{tool_name}'", self.server_config.server_name, tool_settings.mcp_execute_tool_timeout)
#
#    def _check_initialized(self):
#        if not self.initialized:
#            logger.error("MCPClient has not been initialized")
#            raise RuntimeError("MCPClient has not been initialized")
#
#    def cleanup(self):
#        try:
#            for cleanup_func in self.cleanup_funcs:
#                cleanup_func()
#            self.initialized = False
#            if not self.loop.is_closed():
#                self.loop.close()
#        except Exception as e:
#            logger.warning(e)
#        finally:
#            logger.info("Cleaned up MCP clients on shutdown.")
#
#
# class BaseAsyncMCPClient:
#    def __init__(self, server_config: BaseServerConfig):
#        self.server_config = server_config
#        self.session: Optional[ClientSession] = None
#        self.stdio = None
#        self.write = None
#        self.initialized = False
#        self.cleanup_funcs = []
#
#    async def connect_to_server(self):
#
#        success = await self._initialize_connection(self.server_config, timeout=tool_settings.mcp_connect_to_server_timeout)
#
#        if success:
#            self.initialized = True
#        else:
#            raise RuntimeError(
#                f"Connecting to MCP server failed. Please review your server config: {self.server_config.model_dump_json(indent=4)}"
#            )
#
#    async def list_tools(self) -> List[MCPTool]:
#        self._check_initialized()
#        response = await self.session.list_tools()
#        return response.tools
#
#    async def execute_tool(self, tool_name: str, tool_args: dict) -> Tuple[str, bool]:
#        self._check_initialized()
#        result = await self.session.call_tool(tool_name, tool_args)
#
#        parsed_content = []
#        for content_piece in result.content:
#            if isinstance(content_piece, TextContent):
#                parsed_content.append(content_piece.text)
#            else:
#                parsed_content.append(str(content_piece))
#
#            if len(parsed_content) > 0:
#                final_content = " ".join(parsed_content)
#            else:
#                # TODO move hardcoding to constants
#                final_content = "Empty response from tool"
#
#            return final_content, result.isError
#
#    def _check_initialized(self):
#        if not self.initialized:
#            logger.error("MCPClient has not been initialized")
#            raise RuntimeError("MCPClient has not been initialized")
#
#    async def cleanup(self):
#        try:
#            for cleanup_func in self.cleanup_funcs:
#                cleanup_func()
#            self.initialized = False
#            if not self.loop.is_closed():
#                self.loop.close()
#        except Exception as e:
#            logger.warning(e)
#        finally:
#            logger.info("Cleaned up MCP clients on shutdown.")
#
