from datetime import time
import subprocess
from os import chmod, environ, getenv, mkdir, path, remove
from string import Formatter

import yaml
from git import Repo
from bottle import Bottle, post, run, request, response
from dotenv import load_dotenv

load_dotenv()

def get_template_var(text: str):
    return [i[1] for i in Formatter().parse(text) if i[1] is not None]


def build_string(template: str):
    variables = get_template_var(template)
    return template.format(**{var: getenv(var.upper()) for var in variables})


def create_directory(dir_path: str):
    absolute_path = path.abspath(dir_path)
    if not path.exists(absolute_path):
        mkdir(absolute_path)


def get_service(service_name):
    with open("deploy.yml", "r") as stream:
        loaded_file = yaml.load(stream, yaml.Loader)

    services = loaded_file["services"]
    service_info = next(
        (service for service in services if service["name"] == service_name), None
    )

    return service_info


def checkout_git_repo(service):
    repo = None
    if not path.exists(service["working_dir"]):
        yield f"Working directory {service['working_dir']} does not exist\n"
        yield "Cloning repo in desired directory\n"
        repo = Repo.clone_from(
            url=build_string(service["git"]), to_path=service["working_dir"]
        )
    else:
        repo = Repo(service["working_dir"])

    remote = repo.remote("origin")
    yield "Getting updates...\n"
    if service.get('git_force') and service['git_force'] == True:
        repo.heads.master.checkout()
        repo.git.reset('--hard')

    remote.pull(depth=25)
    yield "Update complete\n"


def run_script(service):
    create_directory("./.tmp-repo")
    script_path = path.abspath(
        f"./.tmp-repo/deploy_script_{service['name']}_{str(time())}.sh"
    )
    script_file = None
    process = None

    try:
        script_file = open(script_path, "w")
        script_file.write("#!/usr/bin/env bash\n\n")
        script_file.write(f"cd {service['working_dir']}\n")

        if isinstance(service["script"], list):
            for line in service["script"]:
                script_file.write(f"{line}\n")
        else:
            script_file.write(service["script"])

        script_file.close()
        script_file = None

        chmod(script_path, 0o755)

        process = subprocess.Popen(
            [script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=environ
        )

        for line in process.stdout:
            yield line

        exit_code = process.wait()

        if exit_code == 0:
            yield f"Script executed successfully (exit code: {exit_code})\n"
        else:
            yield f"Script execution failed (exit code: {exit_code})\n"

    except Exception as e:
        yield f"Error executing script: {str(e)}\n"
    finally:
        if script_file:
            script_file.close()
        if process and process.stdout:
            process.stdout.close()
        if path.exists(script_path):
            remove(script_path)


def run_ci(service_name, response):
    service = get_service(service_name)

    if not service:
        response.status = 404
        yield "Service not found\n"
        return

    print(f"Deploying service: {service_name}")

    yield from checkout_git_repo(service)

    if service.get("script"):
        yield from run_script(service)

    yield f"service {service_name} deployed\n"


def deploy():
    auth_key = getenv("DEPLOY_WH_SECRET")
    if not auth_key:
        return "Service not setup correctly"

    auth_header = request.headers.get("Authorization")
    if auth_header:
        token = auth_header.split(" ")[1]
    else:
        token = None
    if token != auth_key:
        response.status = 401
        return "Unauthorized"

    service_name = request.forms.service_name

    if not service_name:
        response.status = 400
        return "Bad user input: service not found"

    response.content_type = "text/plain"
    return run_ci(service_name, response)


app = Bottle()


@app.get("/health")
def wgsi_callback():
    return "Hello, Im alive"


@app.post("/deploy")
def wsgi_callback():
    return deploy()


@post("/deploy")
def callback():
    return deploy()


# This is for local dev
if __name__ == "__main__":
    run(host="0.0.0.0", port=3060, debug=True)
