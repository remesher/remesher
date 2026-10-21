"""Inventory tests use synthetic object_info, not generation evidence."""

import importlib
import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest


@contextmanager
def server(responses):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            status, body = responses.get(self.path, (404, {}))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", requests
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def test_cli_reads_inventory_without_submitting_jobs(capsys):
    from comfy_prompt_cli.native_preflight import main

    nodes, models = inventory_fixture()
    responses = {"/object_info": (200, nodes), "/system_stats": (200, {"devices": []})}
    responses.update(
        {f"/models/{folder}": (200, names) for folder, names in models.items()}
    )
    with server(responses) as (url, requests):
        assert main(["--server", url]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["inventory_ok"] is True
    assert report["hardware_validated"] is False
    assert report["server_stats"] == {"devices": []}
    assert sorted(requests) == sorted(responses)


@pytest.mark.parametrize("response", [(200, []), (200, None), (503, {}), (302, {})])
def test_cli_protocol_failure_is_not_readiness(response, capsys):
    from comfy_prompt_cli.native_preflight import main

    with server({"/system_stats": response}) as (url, _requests):
        assert main(["--server", url]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["inventory_ok"] is False
    assert report["generation_validated"] is False


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://user:password@127.0.0.1",
        "http://127.0.0.1/path",
        "http://localhost:8188",
        "file:///etc/passwd",
    ],
)
def test_cli_rejects_non_loopback_or_ambiguous_urls(url, capsys):
    from comfy_prompt_cli.native_preflight import main

    assert main(["--server", url]) == 2
    assert json.loads(capsys.readouterr().out)["inventory_ok"] is False


@pytest.mark.parametrize(
    "endpoint,response,code",
    [
        ("/object_info", (200, []), 2),
        ("/models/vae", (200, {}), 2),
        ("/models/vae", (200, [None]), 2),
        ("/models/vae", (404, {}), 1),
        ("/object_info", (200, {}), 1),
    ],
)
def test_cli_inventory_failures(endpoint, response, code, capsys):
    from comfy_prompt_cli.native_preflight import main

    nodes, models = inventory_fixture()
    responses = {"/object_info": (200, nodes), "/system_stats": (200, {})}
    responses.update(
        {f"/models/{folder}": (200, names) for folder, names in models.items()}
    )
    responses[endpoint] = response
    with server(responses) as (url, _requests):
        assert main(["--server", url]) == code
    report = json.loads(capsys.readouterr().out)
    assert report["inventory_ok"] is False
    assert report["workflow_api_validated"] is False


def test_missing_native_nodes_fail_closed():
    module = importlib.import_module("comfy_prompt_cli.native_preflight")
    report = module.inspect_inventory({})
    assert report["inventory_ok"] is False
    assert "Trellis2Conditioning" in report["missing_nodes"]
    assert report["generation_validated"] is False


def inventory_fixture():
    from comfy_prompt_cli.native_preflight import CONTRACTS, MANIFEST

    nodes = {name: {} for name in MANIFEST["nodes"]}
    for name, (inputs, outputs) in CONTRACTS.items():
        nodes[name] = {
            "input": {"required": {k: [v] for k, v in inputs.items()}},
            "output": outputs,
        }
    models = {}
    for folder, name in MANIFEST["models"]:
        models.setdefault(folder, []).append(name)
    return nodes, models


def test_inventory_checks_exact_models_and_native_schema():
    from comfy_prompt_cli.native_preflight import inspect_inventory

    nodes, models = inventory_fixture()
    report = inspect_inventory(nodes, models)
    assert report["inventory_ok"] is True
    assert report["generation_validated"] is False
    assert "camera_angle_x" in nodes["Pixal3DConditioning"]["input"]["required"]
    models["diffusion_models"].remove("trellis_2_int8_convrot.safetensors")
    nodes["Trellis2Conditioning"]["input"]["required"]["image"] = ["STRING"]
    report = inspect_inventory(nodes, models)
    assert report["inventory_ok"] is False
    assert report["missing_models"] == [
        "diffusion_models/trellis_2_int8_convrot.safetensors"
    ]
    assert "Trellis2Conditioning.image" in report["schema_mismatches"]


def test_malformed_node_and_models_fail_closed():
    from comfy_prompt_cli.native_preflight import inspect_inventory

    nodes, models = inventory_fixture()
    nodes["Trellis2ShapeStage"] = None
    models["vae"] = "trellis_2_shape_vae_bf16.safetensors"
    report = inspect_inventory(nodes, models)
    assert report["inventory_ok"] is False
    assert "Trellis2ShapeStage" in report["schema_mismatches"]
    assert "vae/trellis_2_shape_vae_bf16.safetensors" in report["missing_models"]
