#!/usr/bin/env node

import { argv } from 'process'
import { writeFileSync } from 'fs'
import { SolidNodeClient } from 'solid-node-client'
import config from 'config'

const data_url = argv[2];
const filename = argv[3];

const credential_config = config.get("credential");
const credential = {
    idp: credential_config['idp'],
    username: credential_config['username'],
    password: credential_config['password']
}

async function getDataAuthenticated(data_url, filename) {
    const client = new SolidNodeClient();
    const session = await client.login(credential);
    if ( session.isLoggedIn ) {
        const response = await client.fetch(data_url);
        const code = await response.text();
        writeFileSync(filename, code);
    }
}

await getDataAuthenticated(data_url, filename);
