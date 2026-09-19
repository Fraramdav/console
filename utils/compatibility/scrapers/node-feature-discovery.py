import re
from collections import OrderedDict

from packaging.version import Version

from utils import (
    current_kube_version,
    expand_kube_versions,
    fetch_page,
    get_github_releases,
    update_compatibility_info,
    validate_semver,
)

app_name = "node-feature-discovery"
repo_owner = "kubernetes-sigs"
repo_name = "node-feature-discovery"
versions_url = (
    "https://raw.githubusercontent.com/kubernetes-sigs/"
    "node-feature-discovery/master/docs/reference/versions.md"
)

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
}


def parse_support_policy(markdown: str) -> tuple[int, str]:
    """Return (supported minor release count, minimum Kubernetes version)."""
    support_match = re.search(
        r"most recent\s+(\w+)\s+minor releases?",
        markdown,
        flags=re.IGNORECASE,
    )
    if not support_match:
        raise ValueError("NFD supported-minor policy not found")

    raw_count = support_match.group(1).lower()
    if raw_count.isdigit():
        supported_minor_count = int(raw_count)
    else:
        supported_minor_count = _NUMBER_WORDS.get(raw_count)
    if not supported_minor_count:
        raise ValueError(f"Unsupported NFD minor-count value: {raw_count}")

    kube_match = re.search(
        r"compatible with Kubernetes\s+v?(\d+\.\d+)\s+and later",
        markdown,
        flags=re.IGNORECASE,
    )
    if not kube_match:
        raise ValueError("NFD minimum Kubernetes version not found")

    return supported_minor_count, kube_match.group(1)


def stable_versions(tags: list[str]) -> list[str]:
    versions = set()
    for tag in tags:
        normalized = tag.strip().lstrip("v")
        semver = validate_semver(normalized)
        if semver:
            versions.add(str(semver))
    return sorted(versions, key=Version, reverse=True)


def select_supported_releases(
    tags: list[str], supported_minor_count: int
) -> list[str]:
    """Select the newest stable patch from each currently supported minor."""
    selected = []
    seen_minors = set()

    for version in stable_versions(tags):
        parsed = Version(version)
        minor_key = (parsed.major, parsed.minor)
        if minor_key in seen_minors:
            continue
        seen_minors.add(minor_key)
        selected.append(version)
        if len(selected) == supported_minor_count:
            break

    if len(selected) != supported_minor_count:
        raise ValueError(
            "Could not identify all currently supported NFD minor releases"
        )

    return selected


def expand_supported_kube_versions(minimum: str, current: str) -> list[str]:
    min_semver = validate_semver(minimum)
    current_semver = validate_semver(current)
    if not min_semver or not current_semver:
        raise ValueError("Invalid Kubernetes version in NFD compatibility policy")
    if current_semver < min_semver:
        raise ValueError(
            f"NFD minimum Kubernetes {minimum} is newer than Plural current {current}"
        )

    return sorted(
        expand_kube_versions(minimum, current),
        key=Version,
        reverse=True,
    )


def build_rows(
    release_tags: list[str],
    current_kube: str,
    minimum_kube: str,
    supported_minor_count: int,
) -> list[OrderedDict]:
    kube_versions = expand_supported_kube_versions(minimum_kube, current_kube)
    releases = select_supported_releases(release_tags, supported_minor_count)

    rows = []
    for version in releases:
        rows.append(
            OrderedDict(
                [
                    ("version", version),
                    ("kube", kube_versions),
                    # NFD publishes a version-matched Helm chart with each release.
                    ("chart_version", version),
                    ("images", []),
                    ("requirements", []),
                    ("incompatibilities", []),
                ]
            )
        )
    return rows


def scrape():
    policy_content = fetch_page(versions_url)
    if not policy_content:
        raise ValueError("Failed to fetch NFD version policy")

    try:
        policy_markdown = policy_content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Could not decode NFD version policy") from exc

    supported_minor_count, minimum_kube = parse_support_policy(policy_markdown)

    current_kube = current_kube_version()
    if not current_kube:
        raise ValueError("Could not determine Plural current Kubernetes version")

    release_tags = get_github_releases(repo_owner, repo_name)
    rows = build_rows(
        release_tags,
        current_kube,
        minimum_kube,
        supported_minor_count,
    )

    update_compatibility_info(
        f"../../static/compatibilities/{app_name}.yaml",
        rows,
    )
