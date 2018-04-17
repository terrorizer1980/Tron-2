#!/usr/bin/env bash


if ! service ssh status > /dev/null; then
  echo Setting up SSH
  apt-get -qq -y install ssh
  service ssh start
fi

if [ -z "$SSH_AUTH_SOCK" ]; then
  echo Setting up SSH agent
  mkdir -p ~/.ssh
  cp example-cluster/insecure_key ~/.ssh/id_rsa
  cp example-cluster/insecure_key.pub ~/.ssh/authorized_keys
  chmod -R 0600 ~/.ssh
  eval $(ssh-agent)
fi

if ! pip3.6 list --format=columns | grep 'tron.*/work' > /dev/null; then
  echo Installing packages
  pip3.6 install -q -e .
fi

echo Starting Tron
rm -f /nail/tron/tron.pid
exec faketime -f '+0.0y x10' trond -l logging.conf --nodaemon --working-dir=/nail/tron -v
