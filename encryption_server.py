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


from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from pathlib import Path
from dataclasses import dataclass
import tempfile
import asyncio
import os
from collections import defaultdict
from uuid import uuid4 as uuid
import json


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


@dataclass
class JobContext:
    client_uuid: str
    proc: asyncio.subprocess.Process
    computation_id: str
    client_id: int
    code_file: Path
    data_file: Path


client_job_pool = {}


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
    client_uuid = str(uuid())
    code_file = save_client_code(job.client_code)
    data_file = await fetch_data(job.data_uri)
    context = await run_client(code_file, data_file, job, client_uuid)
    background_tasks.add_task(clean_workspace, context)
    return client_uuid


@app.get('/client/{client_uuid}')
async def client_status(client_uuid: str, blocking: bool):
    global client_job_pool
    try:
        context = client_job_pool[client_uuid]
        if blocking:
            stdout, stderr = await context.proc.communicate()
        else:
            stdout, stderr = b'', b''
        return_code = context.proc.returncode
        output = stdout.decode()
        return {
                'return_code': return_code,
                'output': output
                }
    except KeyError:
        return json.dumps(client_job_pool)
        # return 404


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
    global client_job_pool
    cmd = [str(e) for e in ['python', code_file, job.client_id, data_file, ','.join(job.player_servers)]]
    command_text = f"cd {BASE_DIR};" + ' '.join(cmd)
    proc = await asyncio.create_subprocess_shell(command_text, stdout=asyncio.subprocess.PIPE)
    context = JobContext(client_uuid, proc, job.computation_id, job.client_id, code_file, data_file)
    client_job_pool[client_uuid] = context
    return context


async def clean_workspace(job_context: JobContext):
    global client_job_pool
    await job_context.proc.wait()
    os.remove(job_context.code_file)
    os.remove(job_context.data_file)
    await asyncio.sleep(60)  # For demonstration, wait 60 seconds before removing the jobs
    del client_job_pool[job_context.client_uuid]
