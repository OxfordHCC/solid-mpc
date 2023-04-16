#!/usr/bin/env python3
# -*- coding:utf-8 -*-

'''
The server that awaits and spawns MPC computation job.

The computation job is received (as Python source code) from the MPC App.
The job does:
    - receive encrypted data from the encryption servers (clients)
    - perform MPC computation
Each server may receive and spawn multiple jobs, but only one of the same computation ID (otherwise compromise can be expected). Randomization of job names (thus source code file names) is needed.
'''

from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from pathlib import Path
import tempfile
import asyncio
import os
import sys
from uuid import uuid4 as uuid
from asyncio import Lock
import json
import datetime
from aiostream.stream import merge


MAX_NUM_PLAYER = 6
PORT_BASE = 5000
if os.environ['PORT_BASE']:
    PORT_BASE = int(os.environ['PORT_BASE'])


CONFIG_FILE = 'config/computation_agent.json'
with open(CONFIG_FILE) as fd:
    _config = json.load(fd)

BASE_DIR = Path(_config['base_dir'])
OUTPUT_LOG = Path(_config['output_log']).absolute() if 'output_log' in _config else None

PLAYER_CODE_DIR = BASE_DIR / 'Programs/Source/'
HOSTS_DIR = BASE_DIR

PROTOCOL_DIR = BASE_DIR

os.chdir(BASE_DIR)

DT_FORMAT = "%Y-%m-%d %H:%M:%S"


class PlayerJob(BaseModel):
    computation_id: str
    num_client: int
    player_id: int
    player_place_id: str
    protocol: Optional[str] = 'shamir'
    player_servers: List[str]
    player_code: str
    data_size: int
    extra_args: Optional[List[str]] = []


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


player_job_pool = {}
free_ports = [True] * MAX_NUM_PLAYER
port_lock = Lock()


@app.put('/allocate_player')
async def allocate_player():
    player_place_id = str(uuid())
    port = -1
    async with port_lock:
        for i in range(MAX_NUM_PLAYER):
            if free_ports[i]:
                port = PORT_BASE + i
                player_job_pool[player_place_id] = i
                free_ports[i] = False
                print(free_ports)
                break
    if port < 0:
        return 500
    return {"player_place_id": player_place_id, "port": port}


@app.put('/player')
def new_player(player_job: PlayerJob, background_tasks: BackgroundTasks):
    background_tasks.add_task(save_compile_run_player, player_job)
    return player_job.player_id


async def wait_and_handle_output(proc, player_job: PlayerJob, prog_and_args):
    full_log = b""

    # See https://stackoverflow.com/questions/50901182/watch-stdout-and-stderr-of-a-subprocess-simultaneously
    async for f in merge(proc.stdout, proc.stderr):
        sys.stderr.write(f"{datetime.datetime.now()} {f.decode()}")
        full_log += f

    log = full_log.decode()
    if player_job.player_id == 0 and OUTPUT_LOG:
        s_now = datetime.datetime.now().strftime(DT_FORMAT)
        run_info = {
            'prog_and_args': prog_and_args,
            'num_player': len(player_job.player_servers),
            'data_size': player_job.data_size,
            'num_client': player_job.num_client,
        }
        line_head = f"###### {s_now} {json.dumps(run_info)} ######\n"
        line_end = "######\n";
        with open(OUTPUT_LOG, 'a') as fd:
            fd.write(line_head)
            fd.write(log)
            fd.write(line_end)


async def save_compile_run_player(player_job: PlayerJob):
    code_file = save_player_code(player_job.player_code)
    code_name = code_file.stem
    hosts_file = save_hosts_file(player_job.player_servers)
    proc_compile, args = await compile_player_code(code_name, player_job)
    await proc_compile.communicate()
    prog_and_args = [code_name] + args
    compiled_code_name = '-'.join(prog_and_args)
    proc_player = await run_player(compiled_code_name, hosts_file, player_job)
    await wait_and_handle_output(proc_player, player_job, prog_and_args)
    await release_port(player_job.player_place_id)
    clean_workspace(code_file, hosts_file)


def save_player_code(player_code: str) -> Path:
    code_file = tempfile.mktemp(prefix='player_code_', suffix='.mpc', dir=PLAYER_CODE_DIR)
    with open(code_file, 'w') as fd:
        fd.write(player_code)
    return Path(code_file)


async def compile_player_code(code_name: str, player_job: PlayerJob):
    num_client = player_job.num_client
    data_size = player_job.data_size
    cmd = ['./compile.py', code_name, num_client, data_size]
    cmd.extend(player_job.extra_args)
    cmd = [str(e) for e in cmd]
    command_text = f"cd {BASE_DIR}; " + ' '.join(cmd)
    proc = await asyncio.subprocess.create_subprocess_shell(command_text)
    return proc, cmd[2:]


def save_hosts_file(player_servers: List[str]) -> Path:
    hosts_file = tempfile.mktemp(prefix='HOSTS_', dir=HOSTS_DIR)
    with open(hosts_file, 'w') as fd:
        fd.write('\n'.join(player_servers))
    return Path(hosts_file)


async def run_player(code_name: str, hosts_file: Path, player_job: PlayerJob):
    protocol_main = PROTOCOL_DIR / f"{player_job.protocol}-party.x"
    cmd = [protocol_main, '-N', len(player_job.player_servers), '-ip', str(hosts_file), player_job.player_id, code_name]
    cmd = [str(e) for e in cmd]
    print('@@', cmd)
    proc = await asyncio.subprocess.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    return proc


async def release_port(player_place_id: str):
    async with port_lock:
        port_index = player_job_pool[player_place_id]
        free_ports[port_index] = True


def clean_workspace(code_file: Path, hosts_file: Path):
    os.remove(code_file)
    os.remove(hosts_file)
