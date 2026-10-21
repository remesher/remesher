"""Protocol fixtures are not inference/hardware certification."""

import struct

import httpx
import pytest

from comfy_prompt_cli import native_backend


def test_json_endpoint_rejects_wrong_payload_type():
    response = httpx.Response(
        200, json=[], request=httpx.Request("GET", "http://127.0.0.1/object_info")
    )
    with pytest.raises(TypeError, match="non-object JSON"):
        native_backend._json(response)


def test_native_graph_is_api_and_maps_backend_overrides():
    graph = native_backend.build_prompt(
        "source.png",
        model="pixal3d",
        mesh_seed=9,
        texture_seed=10,
        target_face_num=1234,
        filename_prefix="result",
        camera_angle=45,
    )
    assert graph["conditioning"]["class_type"] == "Pixal3DConditioning"
    assert graph["conditioning"]["inputs"]["camera_angle_x"] == 45
    assert graph["shape_sample"]["inputs"]["seed"] == 9
    assert graph["texture_sample"]["inputs"]["seed"] == 10
    assert graph["decimate"]["inputs"]["target_face_count"] == 1234
    assert graph["save"]["class_type"] == "SaveGLB"
    assert graph["save"]["inputs"]["filename_prefix"] == "result"
    assert all("class_type" in node and "inputs" in node for node in graph.values())
    assert (
        native_backend.build_prompt("x.png")["conditioning"]["class_type"]
        == "Trellis2Conditioning"
    )


def test_no_decimation_preserves_generated_geometry_and_pbr_graph():
    baseline = native_backend.build_prompt("source.png")
    raw = native_backend.build_prompt("source.png", no_decimation=True)
    expected = dict(baseline)
    del expected["decimate"]
    expected["unwrap"] = {**baseline["unwrap"], "inputs": {
        **baseline["unwrap"]["inputs"], "mesh": ["shape_decode", 0]}}
    assert raw == expected
    assert not any(n["class_type"] == "DecimateMesh" for n in raw.values())


def test_preupload_schema_does_not_require_image_already_on_server():
    graph = {"image": {"class_type": "LoadImage", "inputs": {"image": "new-local.png"}}}
    info = {
        "LoadImage": {
            "input": {
                "required": {"image": [["existing.png"], {"image_upload": True}]}
            },
            "output": ["IMAGE", "MASK"],
        }
    }
    native_backend.validate_prompt(graph, info)


@pytest.mark.parametrize(
    "kind,value",
    [("STRING", 123), ("BOOLEAN", "false"), ("COMFY_DYNAMICCOMBO_V3", "bogus")],
)
def test_schema_rejects_invalid_literals(kind, value):
    graph = {"node": {"class_type": "Node", "inputs": {"value": value}}}
    info = {
        "Node": {
            "input": {
                "required": {
                    "value": [kind, {"options": [{"key": "midpoint", "inputs": {}}]}]
                }
            },
            "output": [],
        }
    }
    with pytest.raises(ValueError):
        native_backend.validate_prompt(graph, info)


def test_missing_forward_node_schema_is_clean_error():
    graph = {
        "a": {"class_type": "A", "inputs": {"source": ["b", 0]}},
        "b": {"class_type": "B", "inputs": {}},
    }
    info = {"A": {"input": {"required": {"source": ["IMAGE"]}}, "output": []}}
    with pytest.raises(ValueError, match="unavailable"):
        native_backend.validate_prompt(graph, info)


@pytest.mark.parametrize(
    "artifact",
    [
        {"filename": "../outside.glb", "subfolder": "", "type": "output"},
        {"filename": "mesh.glb", "subfolder": "../outside", "type": "output"},
        {"filename": "mesh.glb", "subfolder": "", "type": "input"},
        {"filename": "mesh.obj", "subfolder": "", "type": "output"},
    ],
    ids=["filename-traversal", "folder-traversal", "input-artifact", "non-glb"],
)
def test_reject_unsafe_artifacts_without_request(tmp_path, artifact):
    def unexpected(request):
        pytest.fail("unsafe artifact caused HTTP request")

    with (
        httpx.Client(
            base_url="http://127.0.0.1:8188", transport=httpx.MockTransport(unexpected)
        ) as client,
        pytest.raises(ValueError),
    ):
        native_backend._download(client, [artifact], tmp_path)
    assert not list(tmp_path.iterdir())


def test_truncated_artifact_is_removed(tmp_path):
    with (
        httpx.Client(
            base_url="http://127.0.0.1:8188",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"glTF")
            ),
        ) as client,
        pytest.raises(ValueError, match="complete GLB"),
    ):
        native_backend._download(
            client,
            [{"filename": "mesh.glb", "subfolder": "", "type": "output"}],
            tmp_path,
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("status", ["error", "empty", "timeout"])
def test_generation_failure_never_interrupts_shared_server(tmp_path, status):
    image = tmp_path / "source.png"
    image.write_bytes(b"fixture")
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/upload/image":
            return httpx.Response(200, json={"name": "input.png"})
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "job"})
        if request.url.path == "/history/job":
            body = (
                {}
                if status == "timeout"
                else {
                    "job": {
                        "status": {
                            "completed": True,
                            "status_str": "error" if status == "error" else "success",
                        },
                        "outputs": {},
                    }
                }
            )
            return httpx.Response(200, json=body)
        pytest.fail("unexpected API operation")

    with (
        httpx.Client(
            base_url="http://127.0.0.1:8188", transport=httpx.MockTransport(handler)
        ) as client,
        pytest.raises((RuntimeError, ValueError, TimeoutError)),
    ):
        native_backend.generate(
            client,
            image,
            tmp_path / "out",
            validate=False,
            timeout=0.01,
            poll_interval=0.001,
        )
    assert "/interrupt" not in calls and "/view" not in calls


def test_source_checked_api_example_matches_builder():
    import json
    from pathlib import Path

    example = Path(__file__).parents[1] / "examples/img_to_native_trellis2.json"
    assert json.loads(example.read_text()) == native_backend.build_prompt("input.png")


def test_upload_submit_poll_native_3d_history_and_download(tmp_path):
    requests = []
    glb = struct.pack("<4sII", b"glTF", 2, 24) + b"fixture-data"
    image = tmp_path / "source.png"
    image.write_bytes(b"input fixture")

    def handler(request):
        requests.append(request)
        if request.url.path == "/upload/image":
            return httpx.Response(
                200, json={"name": "uploaded.png", "subfolder": "", "type": "input"}
            )
        if request.url.path == "/prompt":
            return httpx.Response(
                200, json={"prompt_id": "owned-job", "node_errors": {}}
            )
        if request.url.path == "/history/owned-job":
            return httpx.Response(
                200,
                json={
                    "owned-job": {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {
                            "save": {
                                "3d": [
                                    {
                                        "filename": "mesh.glb",
                                        "subfolder": "3d",
                                        "type": "output",
                                    }
                                ]
                            }
                        },
                    }
                },
            )
        if request.url.path == "/view":
            assert request.url.params["subfolder"] == "3d"
            return httpx.Response(200, content=glb)
        raise AssertionError(request.url)

    with httpx.Client(
        base_url="http://127.0.0.1:8188", transport=httpx.MockTransport(handler)
    ) as client:
        result = native_backend.generate(
            client, image, tmp_path / "downloads", validate=False
        )
    assert len(result) == 1
    assert result[0].read_bytes() == glb
    import json

    submitted = json.loads(next(r.content for r in requests if r.url.path == "/prompt"))
    assert submitted["prompt"]["image"]["inputs"]["image"] == "uploaded.png"
    assert [r.url.path for r in requests] == [
        "/upload/image",
        "/prompt",
        "/history/owned-job",
        "/view",
    ]
