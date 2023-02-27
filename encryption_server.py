#!/usr/bin/env python3
# -*- coding:utf-8 -*-

'''
The server that awaits and spawns MPC encryption job.
The encryption job is received (as Python source code) from the MPC App.
The job does:
    - send encrypted data to the computation servers
    - read input (raw, possibly private) data from a local file
        - the input file is fetched by data_fetcher, which is called by the job
        - the input file will be deleted after using
Each server may receive and spawn multiple jobs. So randomization of job names (thus source code file names) is needed.
'''


from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi import status
from pydantic import BaseModel
from typing import List, Optional
from pathlib import Path
from dataclasses import dataclass
import tempfile
import asyncio
import os
from collections import defaultdict
from uuid import uuid4 as uuid, UUID
import json
import time


CONFIG_FILE = 'config/encryption_agent.json'
with open(CONFIG_FILE) as fd:
    _config = json.load(fd)

BASE_DIR = Path(_config['base_dir'])

CLIENT_CODE_DIR = BASE_DIR / 'ExternalIO/'
DATA_DOWNLOAD_DIR = BASE_DIR / 'ExternalIO/DownloadData/'


class ClientJob(BaseModel):
    computation_id: str
    data_uri: str
    client_id: int
    client_code: str
    player_servers: List[str]
    data_size: int
    extra_args: Optional[List[str]] = []


@dataclass
class JobContext:
    client_uuid: str
    proc: asyncio.subprocess.Process
    computation_id: str
    client_id: int
    code_file: Path
    data_file: Path


MAX_CONCURRENT_CLIENT_HANDLES = 100
client_handle_pool = asyncio.Queue(MAX_CONCURRENT_CLIENT_HANDLES)

client_job_collection = {}


app = FastAPI()

try:
    origins = _config['allowed_origins']
except KeyError:
    origins = []
finally:
    if not origins:
        origins = ['*']

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get('/')
def read_root():
    return {'Hello': 'World'}


@app.put('/client')
async def new_client(job: ClientJob, background_tasks: BackgroundTasks):
    global client_job_collection
    client_uuid = str(uuid())
    client_job_collection[client_uuid] = None
    background_tasks.add_task(handle_new_client, client_uuid, job)
    return client_uuid


@app.get('/client/{client_uuid}')
async def client_status(client_uuid: str):
    global client_job_collection
    try:
        context = client_job_collection[client_uuid]
        if context is None:
            raise KeyError()
        if context.proc.returncode is None:
            return Response(
                status_code=520,
                content="Not yet finished"
            )
        stdout, stderr = await context.proc.communicate()
        return_code = context.proc.returncode
        output = stdout.decode()
        return {
                'return_code': return_code,
                'output': output
                }
    except KeyError:
        return JSONResponse(
            status_code=520,
            content=json.dumps(list(client_job_collection.keys()))
        )
        # return 404


async def handle_new_client(client_uuid: UUID, job: ClientJob):
    await client_handle_pool.put(True)
    code_file = save_client_code(job.client_code)
    data_file = await fetch_data(job.data_uri)
    context = await run_client(code_file, data_file, job, client_uuid)
    await client_handle_pool.get()
    await clean_workspace(context)


def save_client_code(client_code: str) -> Path:
    code_file = tempfile.mktemp(prefix='client_code_', suffix='.py', dir=CLIENT_CODE_DIR)
    with open(code_file, 'w') as fd:
        fd.write(client_code)
    return Path(code_file)


async def fetch_data(data_uri: str) -> Path:
    data_file = tempfile.mktemp(prefix='data_', suffix='.dat', dir=DATA_DOWNLOAD_DIR)
    # cmd = ['wget', str(data_uri), '-O', data_file]
    cmd = ['env', 'NODE_ENV=encryption_agent', './data_fetcher.js', str(data_uri), str(data_file)]
    proc = await asyncio.create_subprocess_exec(*cmd)
    await proc.communicate()
    return data_file


async def run_client(code_file: Path, data_file: Path, job: ClientJob, client_uuid: str):
    global client_job_collection
    cmd = ['python', code_file, job.client_id, data_file, ','.join(job.player_servers), job.data_size]
    cmd.extend(job.extra_args)
    cmd = [str(e) for e in cmd]
    command_text = f"cd {BASE_DIR};" + ' '.join(cmd)
    proc = await asyncio.create_subprocess_shell(command_text, stdout=asyncio.subprocess.PIPE)
    context = JobContext(client_uuid, proc, job.computation_id, job.client_id, code_file, data_file)
    client_job_collection[client_uuid] = context
    return context


async def clean_workspace(job_context: JobContext):
    global client_job_collection
    await job_context.proc.wait()
    os.remove(job_context.code_file)
    os.remove(job_context.data_file)
    await asyncio.sleep(60)  # For demonstration, wait 60 seconds before removing the jobs
    del client_job_collection[job_context.client_uuid]
