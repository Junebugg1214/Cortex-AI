#!/usr/bin/env python3
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autoresearch_targets.common import ensure_dir, write_json, write_jsonl


HERE = Path(__file__).resolve().parent
CORPUS_DIR = HERE / "corpus"
FIXTURES_DIR = CORPUS_DIR / "fixtures"
SESSIONS_DIR = CORPUS_DIR / "sessions"
MANIFEST_PATH = CORPUS_DIR / "manifest.json"


def user_record(
    content: str,
    cwd: str,
    session_id: str,
    ts: str,
    branch: str = "main",
    version: str = "2.1.37",
) -> dict:
    return {
        "type": "user",
        "uuid": f"user-{session_id}-{ts}",
        "sessionId": session_id,
        "timestamp": ts,
        "cwd": cwd,
        "gitBranch": branch,
        "version": version,
        "message": {"role": "user", "content": content},
    }


def assistant_record(
    tool_uses: list[tuple[str, dict]],
    cwd: str,
    session_id: str,
    ts: str,
    branch: str = "main",
    model: str = "claude-opus-4-1",
) -> dict:
    return {
        "type": "assistant",
        "uuid": f"assistant-{session_id}-{ts}",
        "sessionId": session_id,
        "timestamp": ts,
        "cwd": cwd,
        "gitBranch": branch,
        "message": {
            "role": "assistant",
            "model": model,
            "content": [
                {
                    "type": "tool_use",
                    "id": f"{name}-{index}",
                    "name": name,
                    "input": payload,
                }
                for index, (name, payload) in enumerate(tool_uses, start=1)
            ],
        },
    }


def write_project_files() -> dict[str, Path]:
    ensure_dir(FIXTURES_DIR)

    medchart = FIXTURES_DIR / "medchart"
    ensure_dir(medchart / ".github" / "workflows")
    (medchart / "README.md").write_text(
        "# Medchart\n\n"
        "Medchart helps clinicians review patient charts faster while keeping the audit trail intact.\n",
        encoding="utf-8",
    )
    (medchart / "pyproject.toml").write_text(
        '[project]\nname = "medchart"\ndescription = "Clinician-facing chart review workflow with audit logging."\n'
        'license = "MIT"\n',
        encoding="utf-8",
    )
    (medchart / "LICENSE").write_text("MIT License\n\nPermission is hereby granted...", encoding="utf-8")
    (medchart / ".github" / "workflows" / "test.yml").write_text("name: test\n", encoding="utf-8")

    pulseboard = FIXTURES_DIR / "pulseboard"
    ensure_dir(pulseboard)
    (pulseboard / "README.md").write_text(
        "# Pulseboard\n\n"
        "Pulseboard is a live operations dashboard for tracking incident response and on-call throughput.\n",
        encoding="utf-8",
    )
    (pulseboard / "package.json").write_text(
        "{\n"
        '  "name": "pulseboard",\n'
        '  "description": "Real-time operations dashboard for customer support teams.",\n'
        '  "license": "Apache-2.0",\n'
        '  "keywords": ["operations", "dashboard", "realtime"],\n'
        '  "devDependencies": {"typescript": "^5.7.0"}\n'
        "}\n",
        encoding="utf-8",
    )
    (pulseboard / "Dockerfile").write_text("FROM node:20\n", encoding="utf-8")

    opskit = FIXTURES_DIR / "opskit"
    ensure_dir(opskit)
    (opskit / "README.md").write_text(
        "# Opskit\n\n"
        "Opskit packages deployment automation for Kubernetes services, Docker builds, and AWS rollouts.\n",
        encoding="utf-8",
    )
    (opskit / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")

    shopflow = FIXTURES_DIR / "shopflow"
    ensure_dir(shopflow)
    (shopflow / "README.md").write_text(
        "# Shopflow\n\n"
        "Shopflow coordinates checkout orchestration across a Python API and a TypeScript storefront.\n",
        encoding="utf-8",
    )
    (shopflow / "package.json").write_text(
        "{\n"
        '  "name": "shopflow",\n'
        '  "description": "Unified checkout workflow for catalog, cart, and payments.",\n'
        '  "license": "MIT",\n'
        '  "keywords": ["checkout", "payments", "commerce"],\n'
        '  "devDependencies": {"typescript": "^5.7.0"}\n'
        "}\n",
        encoding="utf-8",
    )

    auditmesh = FIXTURES_DIR / "auditmesh"
    ensure_dir(auditmesh)
    (auditmesh / "README.md").write_text(
        "# Auditmesh\n\n"
        "Auditmesh builds tamper-evident audit trails for compliance-heavy product teams.\n",
        encoding="utf-8",
    )
    (auditmesh / "Cargo.toml").write_text(
        '[package]\nname = "auditmesh"\ndescription = "Tamper-evident audit trail service for compliance teams."\n'
        'license = "Apache-2.0"\n',
        encoding="utf-8",
    )
    (auditmesh / "LICENSE").write_text("Apache License Version 2.0\n", encoding="utf-8")

    tinytask = FIXTURES_DIR / "tinytask"
    ensure_dir(tinytask)
    (tinytask / "README.md").write_text("# Tinytask\n\nTinytask.\n", encoding="utf-8")

    uvservice = FIXTURES_DIR / "uvservice"
    ensure_dir(uvservice)
    (uvservice / "README.md").write_text(
        "# uvservice\n\n"
        "uvservice is a lightweight API prototype managed with uv and pytest.\n",
        encoding="utf-8",
    )
    (uvservice / "pyproject.toml").write_text(
        '[project]\nname = "uvservice"\ndescription = "Small API service managed with uv for fast local workflows."\n'
        'license = "MIT"\n',
        encoding="utf-8",
    )
    (uvservice / "LICENSE").write_text("MIT License\n", encoding="utf-8")

    return {
        "medchart": medchart,
        "pulseboard": pulseboard,
        "opskit": opskit,
        "shopflow": shopflow,
        "auditmesh": auditmesh,
        "tinytask": tinytask,
        "uvservice": uvservice,
    }


def build_sessions(projects: dict[str, Path]) -> list[dict]:
    ensure_dir(SESSIONS_DIR)
    manifest_cases: list[dict] = []

    medchart_path = str(projects["medchart"])
    medchart_session = SESSIONS_DIR / "test_01_medchart.jsonl"
    write_jsonl(
        medchart_session,
        [
            user_record("Plan the auth fix before touching the code.", medchart_path, "medchart-1", "2026-02-08T10:00:00.000Z"),
            assistant_record([("EnterPlanMode", {})], medchart_path, "medchart-1", "2026-02-08T10:00:30.000Z"),
            assistant_record(
                [
                    ("Read", {"file_path": f"{medchart_path}/auth.py"}),
                    ("Edit", {"file_path": f"{medchart_path}/auth.py", "old_string": "bug", "new_string": "fix"}),
                    ("Write", {"file_path": f"{medchart_path}/tests/test_auth.py", "content": "assert True"}),
                    ("Bash", {"command": "pytest tests/test_auth.py -q"}),
                    ("Bash", {"command": "git status"}),
                ],
                medchart_path,
                "medchart-1",
                "2026-02-08T10:05:00.000Z",
            ),
        ],
    )
    manifest_cases.append(
        {
            "id": "test_01_medchart_planning",
            "description": "Python planning session with tests and pyproject enrichment.",
            "session_files": [str(medchart_session)],
            "enrich": True,
            "expected_topics": {
                "technical_expertise": ["Python", "Pytest", "Git"],
                "user_preferences": ["Plans before coding", "Writes tests"],
                "active_priorities": ["medchart"],
                "domain_knowledge": ["medchart purpose"],
            },
            "expected_text": {
                "active_priorities": ["License: MIT", "Manifest: pyproject.toml", "CI/CD configured"],
                "domain_knowledge": ["chart review workflow"],
            },
            "forbidden_topics": ["Rust", "TypeScript"],
        }
    )

    pulseboard_path = str(projects["pulseboard"])
    pulseboard_session = SESSIONS_DIR / "test_02_pulseboard.jsonl"
    write_jsonl(
        pulseboard_session,
        [
            user_record("Add a realtime widget to the dashboard.", pulseboard_path, "pulseboard-1", "2026-02-09T09:00:00.000Z"),
            assistant_record(
                [
                    ("Read", {"file_path": f"{pulseboard_path}/package.json"}),
                    ("Write", {"file_path": f"{pulseboard_path}/src/App.tsx", "content": "export function App() {}"}),
                    ("Write", {"file_path": f"{pulseboard_path}/src/App.spec.tsx", "content": "it('works', () => {})"}),
                    ("Bash", {"command": "pnpm test"}),
                    ("Bash", {"command": "pnpm build"}),
                    ("Bash", {"command": "git diff --stat"}),
                ],
                pulseboard_path,
                "pulseboard-1",
                "2026-02-09T09:04:00.000Z",
            ),
        ],
    )
    manifest_cases.append(
        {
            "id": "test_02_pulseboard_frontend",
            "description": "TypeScript dashboard project with package.json and Docker enrichment.",
            "session_files": [str(pulseboard_session)],
            "enrich": True,
            "expected_topics": {
                "technical_expertise": ["TypeScript", "Node.js", "pnpm", "Git"],
                "user_preferences": ["Writes tests"],
                "active_priorities": ["pulseboard"],
                "domain_knowledge": ["pulseboard purpose"],
            },
            "expected_text": {
                "active_priorities": ["License: Apache-2.0", "Manifest: package.json", "Docker configured"],
                "domain_knowledge": ["operations dashboard"],
            },
            "forbidden_topics": ["Rust", "Kubernetes"],
        }
    )

    opskit_path = str(projects["opskit"])
    opskit_session = SESSIONS_DIR / "test_03_opskit.jsonl"
    write_jsonl(
        opskit_session,
        [
            user_record("Wire up the rollout automation.", opskit_path, "opskit-1", "2026-02-10T11:00:00.000Z"),
            assistant_record(
                [
                    ("Read", {"file_path": f"{opskit_path}/Dockerfile"}),
                    ("Write", {"file_path": f"{opskit_path}/deploy/service.yaml", "content": "kind: Deployment"}),
                    ("Write", {"file_path": f"{opskit_path}/scripts/release.sh", "content": "#!/usr/bin/env bash"}),
                    ("Bash", {"command": "kubectl apply -f deploy/service.yaml"}),
                    ("Bash", {"command": "aws ecs update-service --cluster prod --service api"}),
                    ("Bash", {"command": "docker build -t opskit ."}),
                ],
                opskit_path,
                "opskit-1",
                "2026-02-10T11:06:00.000Z",
            ),
        ],
    )
    manifest_cases.append(
        {
            "id": "test_03_opskit_infra",
            "description": "Infra session with Kubernetes, AWS CLI, Docker, YAML, and shell files.",
            "session_files": [str(opskit_session)],
            "enrich": True,
            "expected_topics": {
                "technical_expertise": ["YAML", "Shell", "Docker", "Kubernetes", "AWS CLI"],
                "active_priorities": ["opskit"],
                "domain_knowledge": ["opskit purpose"],
            },
            "expected_text": {
                "active_priorities": ["Docker configured"],
                "domain_knowledge": ["deployment automation"],
            },
            "forbidden_topics": ["TypeScript", "Writes tests"],
        }
    )

    shopflow_path = str(projects["shopflow"])
    shopflow_session_a = SESSIONS_DIR / "test_04_shopflow_backend.jsonl"
    shopflow_session_b = SESSIONS_DIR / "test_04_shopflow_frontend.jsonl"
    write_jsonl(
        shopflow_session_a,
        [
            user_record("Sketch the API plan first, then patch checkout.", shopflow_path, "shopflow-a", "2026-02-11T08:00:00.000Z"),
            assistant_record([("EnterPlanMode", {})], shopflow_path, "shopflow-a", "2026-02-11T08:00:20.000Z"),
            assistant_record(
                [
                    ("Write", {"file_path": f"{shopflow_path}/api/app.py", "content": "def app():\n    return True"}),
                    ("Write", {"file_path": f"{shopflow_path}/tests/test_checkout.py", "content": "assert True"}),
                    ("Bash", {"command": "pytest tests/test_checkout.py"}),
                ],
                shopflow_path,
                "shopflow-a",
                "2026-02-11T08:05:00.000Z",
            ),
        ],
    )
    write_jsonl(
        shopflow_session_b,
        [
            user_record("Hook the storefront into the checkout API.", shopflow_path, "shopflow-b", "2026-02-11T09:00:00.000Z"),
            assistant_record(
                [
                    ("Read", {"file_path": f"{shopflow_path}/package.json"}),
                    ("Write", {"file_path": f"{shopflow_path}/web/src/Checkout.tsx", "content": "export const Checkout = () => null"}),
                    ("Bash", {"command": "pnpm lint"}),
                ],
                shopflow_path,
                "shopflow-b",
                "2026-02-11T09:03:00.000Z",
            ),
        ],
    )
    manifest_cases.append(
        {
            "id": "test_04_shopflow_multi_session",
            "description": "Aggregate two sessions into one full-stack project context.",
            "session_files": [str(shopflow_session_a), str(shopflow_session_b)],
            "enrich": True,
            "expected_topics": {
                "technical_expertise": ["Python", "TypeScript", "Node.js", "Pytest", "pnpm"],
                "user_preferences": ["Plans before coding", "Writes tests"],
                "active_priorities": ["shopflow"],
                "domain_knowledge": ["shopflow purpose"],
            },
            "expected_text": {
                "active_priorities": ["Manifest: package.json", "Keywords: checkout, payments, commerce"],
                "domain_knowledge": ["checkout workflow"],
            },
            "forbidden_topics": ["Rust", "Kubernetes"],
        }
    )

    auditmesh_path = str(projects["auditmesh"])
    auditmesh_session = SESSIONS_DIR / "test_05_auditmesh.jsonl"
    write_jsonl(
        auditmesh_session,
        [
            user_record("Add the audit hashing module.", auditmesh_path, "auditmesh-1", "2026-02-12T07:00:00.000Z"),
            assistant_record(
                [
                    ("Read", {"file_path": f"{auditmesh_path}/Cargo.toml"}),
                    ("Write", {"file_path": f"{auditmesh_path}/src/lib.rs", "content": "pub fn hash() {}"}),
                    ("Write", {"file_path": f"{auditmesh_path}/src/main.rs", "content": "fn main() {}"}),
                    ("Bash", {"command": "cargo test"}),
                    ("Bash", {"command": "cargo fmt"}),
                ],
                auditmesh_path,
                "auditmesh-1",
                "2026-02-12T07:04:00.000Z",
            ),
        ],
    )
    manifest_cases.append(
        {
            "id": "test_05_auditmesh_manifest",
            "description": "Rust project with Cargo manifest and license enrichment.",
            "session_files": [str(auditmesh_session)],
            "enrich": True,
            "expected_topics": {
                "technical_expertise": ["Rust", "Cargo"],
                "active_priorities": ["auditmesh"],
                "domain_knowledge": ["auditmesh purpose"],
            },
            "expected_text": {
                "active_priorities": ["License: Apache-2.0", "Manifest: Cargo.toml", "Languages: Rust"],
                "domain_knowledge": ["audit trail service"],
            },
            "forbidden_topics": ["TypeScript", "Writes tests"],
        }
    )

    tinytask_path = str(projects["tinytask"])
    tinytask_session = SESSIONS_DIR / "test_06_tinytask_sparse.jsonl"
    write_jsonl(
        tinytask_session,
        [
            user_record("Trim the shell script.", tinytask_path, "tinytask-1", "2026-02-13T06:00:00.000Z"),
            assistant_record(
                [
                    ("Write", {"file_path": f"{tinytask_path}/scripts/cleanup.sh", "content": "echo cleanup"}),
                ],
                tinytask_path,
                "tinytask-1",
                "2026-02-13T06:01:00.000Z",
            ),
        ],
    )
    manifest_cases.append(
        {
            "id": "test_06_tinytask_sparse",
            "description": "Sparse shell-only session should stay narrow and avoid extra behavior nodes.",
            "session_files": [str(tinytask_session)],
            "enrich": True,
            "expected_topics": {
                "technical_expertise": ["Shell"],
                "active_priorities": ["tinytask"],
            },
            "expected_text": {},
            "forbidden_topics": ["Python", "TypeScript", "Writes tests", "Plans before coding"],
        }
    )

    uvservice_path = str(projects["uvservice"])
    uvservice_session = SESSIONS_DIR / "test_07_uvservice.jsonl"
    write_jsonl(
        uvservice_session,
        [
            user_record("Add the API smoke test and keep the uv workflow intact.", uvservice_path, "uvservice-1", "2026-02-14T06:00:00.000Z"),
            assistant_record(
                [
                    ("Read", {"file_path": f"{uvservice_path}/pyproject.toml"}),
                    ("Write", {"file_path": f"{uvservice_path}/app/api.py", "content": "def api():\n    return True"}),
                    ("Write", {"file_path": f"{uvservice_path}/tests/test_api.py", "content": "assert True"}),
                    ("Bash", {"command": "uv sync"}),
                    ("Bash", {"command": "uv run pytest tests/test_api.py"}),
                ],
                uvservice_path,
                "uvservice-1",
                "2026-02-14T06:04:00.000Z",
            ),
        ],
    )
    manifest_cases.append(
        {
            "id": "test_07_uvservice_modern_python",
            "description": "Modern Python session should retain uv as a first-class tooling signal.",
            "session_files": [str(uvservice_session)],
            "enrich": True,
            "expected_topics": {
                "technical_expertise": ["Python", "Pytest", "uv"],
                "user_preferences": ["Writes tests"],
                "active_priorities": ["uvservice"],
                "domain_knowledge": ["uvservice purpose"],
            },
            "expected_text": {
                "active_priorities": ["License: MIT", "Manifest: pyproject.toml"],
                "domain_knowledge": ["managed with uv"],
            },
            "forbidden_topics": ["Rust", "pnpm"],
        }
    )

    return manifest_cases


def main() -> None:
    ensure_dir(CORPUS_DIR)
    projects = write_project_files()
    cases = build_sessions(projects)
    manifest = {
        "target": "extract_coding",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": cases,
    }
    write_json(MANIFEST_PATH, manifest)
    print(f"Wrote coding corpus to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
