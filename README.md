MPC on Solid

- - - - - -

MPC on Solid (or Solid-like decentralized settings).

This directory contains the server code, i.e. the code for the encryption agent and the computation agent.

Refer to [`mpc-app`](https://github.com/OxfordHCC/solid-mpc-app) for the companion Solid App for the end users (who want to initiate MPC).

## How to run

### Preparation

You should correctly set up the MP-SPDZ environment beforehand (not documented here, see MP-SPDZ's doc). Then, you should install the relevant dependencies, as stated in this section, before running the agent services.

For both type of agents, you need to install Python dependencies to run the API endpoint (service):

```
pip install -r requirements.txt
```

For Encryption Agent, you also need to install nodejs dependencies to use data fetcher:

```
npm install
```

### Automated

Use [tmuxp](https://github.com/tmux-python/tmuxp):

```
tmuxp load tmux_sessions.yaml
```

This will start two encryption agents (listening on port 8000 and 8001), three computation agents (listening on port 8010, 8011, 8012) and the Solid App on local machine.

Internally, the computation agents will use port base 5000, 5010 and 5020 to run the MPC players.

### Manual

You need to run encryption agents (`encryption_server.py`) and computation agents (`computation_server`) depending on your need. Each machine/server is expected to run only one encryption agent, or one computation agent.

#### Run encryption server(s)

```
uvicorn encryption_server:app --port 8000 --reload
```

Run separate servers by changing the port number.

Remember to configure the authentication credentials as stated later.

#### Run computation server(s)

```
PORT_BASE=5000 uvicorn computation_server:app --port 8010
```

Run separate servers by changing the port number.

You will also want to change `PORT_BASE` if you are testing locally, otherwise there will be port conflicts (of the running MPC circuit) between server instances. The example uses 5000, 5010 and 5020 as the port bases, which allows each agent to run 10 MPC tasks simultaneously.

## Server configuration

Both the encryption agent and computation agent needs to have a meaningful configuration file. In particular, the `base_dir` needs to be the base directory of the local MP-SPDZ installation.

### Encryption agent

Configuration file locate at `config/encryption_agent.json`. Open and modify it to match your setup.

#### Authentication

The encryption agent will use an authenticated fetch to retrieve data from user pods. 

Our implementaion uses [solid-node-client](https://github.com/solid-contrib/solid-node-client) to authenticate the agent as a WebID. Therefore, you need to create a WebID for your encryption agent (or multiple of them) by registering a pod for it.

Then, add `https://solid-node-client` to the list of trusted apps for the agent user.

Finally, change the content of `config/encryption_agent.json` to match your agent user: IDP (usually the server address where the agent user is registered), username, and password.

#### Other

You need to manually create the directory: `MP-SPDZ/ExternalIO/DownloadData`, where the downloaded data are stored.

### Computaion agent

Configuration file locate at `config/computation_agent.json`. Open and modify it to match your setup.

## User/Pod configuration

The encryption agent(s) will need to fetch data from the data providers, and then securely send shares of the data to the computation agents. Therefore, the user will need to ensure appropriate permission is set to allow the encryption agent to access the data. Refer to the [README of mpc-app](https://github.com/OxfordHCC/solid-mpc-app/blob/master/README.md) for details.
