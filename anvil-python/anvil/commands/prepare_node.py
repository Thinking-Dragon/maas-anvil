# Copyright (c) 2024 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import click
from rich.console import Console

from anvil.utils import FormatEpilogCommand

console = Console()


JUJU_CHANNEL = "3.4/stable"
SUPPORTED_RELEASE = "jammy"

PREPARE_NODE_TEMPLATE = f"""#!/bin/bash
[ $(lsb_release -sc) != '{SUPPORTED_RELEASE}' ] && \
{{ echo 'ERROR: MAAS Anvil deploy only supported on {SUPPORTED_RELEASE}'; exit 1; }}

# :warning: Node Preparation for MAAS Anvil :warning:
# All of these commands perform privileged operations
# please review carefully before execution.
USER=$(whoami)

if [ $(id -u) -eq 0 -o "$USER" = root ]; then
    cat << EOF
ERROR: Node Preparation script for Anvil must be executed by
       non-root user with sudo permissions.
EOF
    exit 1
fi

# Check if user has passwordless sudo permissions and setup if need be
SUDO_ASKPASS=/bin/false sudo -A whoami &> /dev/null &&
sudo grep -r $USER /etc/{{sudoers,sudoers.d}} | grep NOPASSWD:ALL &> /dev/null || {{
    echo "$USER ALL=(ALL) NOPASSWD:ALL" > /tmp/90-$USER-sudo-access
    sudo install -m 440 /tmp/90-$USER-sudo-access /etc/sudoers.d/90-$USER-sudo-access
    rm -f /tmp/90-$USER-sudo-access
}}

# Ensure OpenSSH server is installed
dpkg -s openssh-server &> /dev/null || {{
    sudo apt install -y openssh-server
}}

# Connect snap to the ssh-keys interface to allow
# read access to private keys - this supports bootstrap
# of the Juju controller to the local machine via SSH.
sudo snap connect maas-anvil:ssh-keys

# Add $USER to the snap_daemon group supporting interaction
# with the MAAS Anvil clustering daemon for cluster operations.
sudo addgroup $USER snap_daemon

# Generate keypair and set-up prompt-less access to local machine
[ -f $HOME/.ssh/id_rsa ] || ssh-keygen -b 4096 -f $HOME/.ssh/id_rsa -t rsa -N ""
cat $HOME/.ssh/id_rsa.pub >> $HOME/.ssh/authorized_keys
ssh-keyscan -H $(hostname --all-ip-addresses) >> $HOME/.ssh/known_hosts

# Install the Juju snap
sudo snap install --channel {JUJU_CHANNEL} juju

# Workaround a bug between snapd and juju
mkdir -p $HOME/.local/share
mkdir -p $HOME/.config/anvil

# Connect snap to the Juju snap interface and provide access to Juju directory.
# These actions will allow anvil bootstrap Juju controller and manage the
# Juju model.
sudo snap connect maas-anvil:juju-bin juju:juju-bin
sudo snap connect maas-anvil:dot-local-share-juju
sudo snap connect maas-anvil:dot-config-anvil
"""


@click.command(
    cls=FormatEpilogCommand,
    epilog="""
    \b
    Prepare a node for usage with MAAS Anvil by generating the 'prepare-node-script' and
    running it immediately by piping it to bash.
    maas-anvil prepare-node-script | bash -x
    """,
)
@click.option(
    '--additional-dependency',
    required=False,
    multiple=True,
    help='Include additional snap dependency, format: `snap-name:snap-channel`'
)
def prepare_node_script(additional_dependency: tuple) -> None:
    """Generates a script to prepare the node for use with MAAS Anvil.
    This must be run on every node on which you want to use MAAS Anvil."""
    script = PREPARE_NODE_TEMPLATE

    dependencies = additional_dependency # Alias because the argument must match the option name
    if dependencies:
        script += '\n'

        for raw_dependency in dependencies:
            try:
                name, channel = _try_parse_dependency(raw_dependency)

                script += f"# Install the {name} snap\n"
                script += f"sudo snap install --channel {channel} {name}\n\n"

            except Exception as error_message:
                console.print(error_message)
                return

    console.print(script, soft_wrap=True)

def _try_parse_dependency(raw_dependency: str) -> tuple[str]:
    nb_expected_tokens = 2
    tokens = raw_dependency.split(':')

    if len(tokens) != nb_expected_tokens:
        raise Exception(f"Additional dependency \"{raw_dependency}\" is badly formatted. Should be: `snap-name:snap-channel`.")

    name = tokens[0]
    channel = tokens[1]

    return name, channel
