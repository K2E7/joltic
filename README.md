# Joltic

Single-file interactive SSH launcher for SIT/UAT/PFIX environments. Everything
ships inside the `joltic` script so Clinton can install it without extra build
steps.

## Usage

Install globally with [Clinton](https://github.com/K2E7/clinton):

```bash
clinton install joltic
```

Then connect to servers via:

```bash
joltic
joltic SIT
joltic UAT batches
joltic --config         # launches the interactive config wizard
joltic --config my.json # imports my.json and makes it the active config
```

Configuration lives in `~/.joltic/config.json` (falls back to `./.joltic/`
whenever the home directory is not writable). You can also supply an explicit
file with `joltic --config my_config.json` to validate it, store it in the
default location, and exit without opening an SSH session. The CLI prints a
confirmation so you know the settings were loaded.

### Configuration format

`config.json` is a simple object with two keys:

```json
{
  "aliases": {
    "SIT": ["QA", "TEST"],
    "UAT": ["STAGING"]
  },
  "servers": {
    "SIT": {
      "batches": [
        {"name": "batch1", "host": "sit-batch1.company.com", "user": "ec2-user"},
        {"name": "batch2", "host": "sit-batch2.company.com", "user": "ec2-user", "port": 2222 }
      ],
      "webapps": [
        {"name": "web1", "host": "sit-web1.company.com"}
      ]
    }
  }
}
```

- `aliases` maps the canonical environment (e.g., `SIT`) to any number of alternative names you want the CLI to understand.
- `servers` nests environments → categories → server entries. Each server entry must have `name` and `host`, and may include optional `user` and `port` fields. Additional keys are passed verbatim to the interactive picker so you can extend the schema for your own tooling.

You do not need to craft the file by hand — run `joltic --config` with no value to launch the interactive wizard which guides you through adding environments, categories, and server definitions.

### CLI flags

- `environment` / `category` positional arguments narrow the interactive prompts. You can type either a canonical name or any alias.
- `--config PATH` imports and validates a configuration file, writes it to the default location, prints a confirmation, and exits without attempting an SSH connection. Supplying the flag without a value opens the configuration wizard and saves the result to the default location.
- `--ssh-arg VALUE` forwards extra options to `ssh`. Repeat the flag for multiple options (for instance `--ssh-arg -i --ssh-arg ~/.ssh/work.pem`).
- `--dry-run` prints the fully expanded ssh command so you can verify it before execution, which is handy for shell history or troubleshooting.

Exit codes are conventional: `0` for success, `2` when the configuration cannot be read/validated, `3` for bad environment/category/server selections, and the ssh process' exit status otherwise.

### Logging and troubleshooting

Every invocation writes to `~/.joltic/connect.log` (or `./.joltic/connect.log` if the home directory is not writable). The log includes resolution steps and the exact ssh command that was launched, making it easier to copy/paste or audit connections later. Use `JOLTIC_HOME=/custom/path joltic ...` to override both the configuration and log directory if you need the tool to operate inside a portable workspace.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./joltic --help
```

The only runtime dependency is `questionary` for the richer interactive prompts;
if it is missing the CLI automatically falls back to simple text prompts.
