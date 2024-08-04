import os
import tempfile
import uuid
from functools import partial
from typing import List

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from memgpt.data_sources.connectors import DirectoryConnector

# from memgpt.data_types import Source
from memgpt.schemas.document import Document as DocumentModel  # TODO: modify
from memgpt.schemas.enums import JobStatus
from memgpt.schemas.job import Job as JobModel  # TODO: modify
from memgpt.schemas.passage import Passage as PassageModel  # TODO: modify
from memgpt.schemas.source import Source, SourceAttach, SourceCreate, SourceDetach
from memgpt.server.rest_api.auth_token import get_current_user
from memgpt.server.rest_api.interface import QueuingInterface
from memgpt.server.server import SyncServer

router = APIRouter()

"""
Implement the following functions:
* List all available sources
* Create a new source
* Delete a source
* Upload a file to a server that is loaded into a specific source
* Paginated get all passages from a source
* Paginated get all documents from a source
* Attach a source to an agent
"""


class GetSourcePassagesResponse(BaseModel):
    passages: List[PassageModel] = Field(..., description="List of passages from the source.")


class GetSourceDocumentsResponse(BaseModel):
    documents: List[DocumentModel] = Field(..., description="List of documents from the source.")


def load_file_to_source(server: SyncServer, user_id: uuid.UUID, source: Source, job_id: uuid.UUID, file: UploadFile, bytes: bytes):
    # update job status
    job = server.ms.get_job(job_id=job_id)
    job.status = JobStatus.running
    server.ms.update_job(job)

    try:
        # write the file to a temporary directory (deleted after the context manager exits)
        with tempfile.TemporaryDirectory() as tmpdirname:
            file_path = os.path.join(tmpdirname, file.filename)
            with open(file_path, "wb") as buffer:
                buffer.write(bytes)

            # read the file
            connector = DirectoryConnector(input_files=[file_path])

            # TODO: pre-compute total number of passages?

            # load the data into the source via the connector
            num_passages, num_documents = server.load_data(user_id=user_id, source_name=source.name, connector=connector)
    except Exception as e:
        # job failed with error
        error = str(e)
        print(error)
        job.status = JobStatus.failed
        job.metadata_["error"] = error
        server.ms.update_job(job)
        # TODO: delete any associated passages/documents?
        return 0, 0

    # update job status
    job.status = JobStatus.completed
    job.metadata_["num_passages"] = num_passages
    job.metadata_["num_documents"] = num_documents
    print("job completed", job.metadata_, job.id)
    server.ms.update_job(job)


def setup_sources_index_router(server: SyncServer, interface: QueuingInterface, password: str):
    get_current_user_with_server = partial(partial(get_current_user, server), password)

    @router.get("/sources", tags=["sources"], response_model=List[Source])
    async def list_sources(
        user_id: uuid.UUID = Depends(get_current_user_with_server),
    ):
        """
        List all data sources created by a user.
        """
        interface.clear()

        try:
            return server.list_all_sources(user_id=str(user_id))
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"{e}")

    @router.post("/sources", tags=["sources"], response_model=Source)
    async def create_source(
        request: SourceCreate = Body(...),
        user_id: uuid.UUID = Depends(get_current_user_with_server),
    ):
        """
        Create a new data source.
        """
        interface.clear()

        try:
            return server.create_source(name=request.name, user_id=user_id)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"{e}")

    @router.delete("/sources/{source_id}", tags=["sources"])
    async def delete_source(
        source_id: uuid.UUID,
        user_id: uuid.UUID = Depends(get_current_user_with_server),
    ):
        """
        Delete a data source.
        """
        interface.clear()

        try:
            server.delete_source(source_id=source_id, user_id=user_id)
            return JSONResponse(status_code=status.HTTP_200_OK, content={"message": f"Source source_id={source_id} successfully deleted"})
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"{e}")

    @router.post("/sources/{source_id}/attach", tags=["sources"], response_model=Source)
    async def attach_source_to_agent(
        # request: SourceAttach = Body(...),
        source_id: uuid.UUID,
        agent_id: uuid.UUID = Query(..., description="The unique identifier of the agent to attach the source to."),
        user_id: uuid.UUID = Depends(get_current_user_with_server),
    ):
        """
        Attach a data source to an existing agent.
        """
        interface.clear()

        try:
            # TODO remove pydantic model?
            request = SourceAttach(agent_id=agent_id, source_id=source_id)
            return server.attach_source_to_agent(source_id=source_id, agent_id=agent_id, user_id=user_id)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"{e}")

    @router.post("/sources/{source_id}/detach", tags=["sources"], response_model=Source)
    async def detach_source_from_agent(
        source_id: uuid.UUID,
        agent_id: uuid.UUID = Query(..., description="The unique identifier of the agent to detach the source from."),
        user_id: uuid.UUID = Depends(get_current_user_with_server),
    ):
        """
        Detach a data source from an existing agent.
        """
        interface.clear()

        try:
            # TODO remove pydantic model?
            request = SourceDetach(agent_id=agent_id, source_id=source_id)
            return server.detach_source_from_agent(source_id=source_id, agent_id=agent_id, user_id=user_id)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"{e}")

    @router.get("/sources/status/{job_id}", tags=["sources"], response_model=JobModel)
    async def get_job_status(
        job_id: uuid.UUID,
        user_id: uuid.UUID = Depends(get_current_user_with_server),
    ):
        """
        Get the status of a job.
        """
        job = server.ms.get_job(job_id=job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job with id={job_id} not found.")
        return job

    @router.post("/sources/{source_id}/upload", tags=["sources"], response_model=JobModel)
    async def upload_file_to_source(
        # file: UploadFile = UploadFile(..., description="The file to upload."),
        file: UploadFile,
        source_id: uuid.UUID,
        background_tasks: BackgroundTasks,
        user_id: uuid.UUID = Depends(get_current_user_with_server),
    ):
        """
        Upload a file to a data source.
        """
        interface.clear()
        source = server.ms.get_source(source_id=source_id, user_id=user_id)
        bytes = file.file.read()

        # create job
        job = JobModel(user_id=user_id, metadata={"type": "embedding", "filename": file.filename, "source_id": source_id})
        job_id = job.id
        server.ms.create_job(job)

        # create background task
        background_tasks.add_task(load_file_to_source, server, user_id, source, job_id, file, bytes)

        # return job information
        job = server.ms.get_job(job_id=job_id)
        return job

    @router.get("/sources/{source_id}/passages ", tags=["sources"], response_model=GetSourcePassagesResponse)
    async def list_passages(
        source_id: uuid.UUID,
        user_id: uuid.UUID = Depends(get_current_user_with_server),
    ):
        """
        List all passages associated with a data source.
        """
        passages = server.list_data_source_passages(user_id=user_id, source_id=source_id)
        return GetSourcePassagesResponse(passages=passages)

    @router.get("/sources/{source_id}/documents", tags=["sources"], response_model=GetSourceDocumentsResponse)
    async def list_documents(
        source_id: uuid.UUID,
        user_id: uuid.UUID = Depends(get_current_user_with_server),
    ):
        """
        List all documents associated with a data source.
        """
        documents = server.list_data_source_documents(user_id=user_id, source_id=source_id)
        return GetSourceDocumentsResponse(documents=documents)

    return router
