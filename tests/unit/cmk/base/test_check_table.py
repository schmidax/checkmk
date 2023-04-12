#!/usr/bin/env python3
# Copyright (C) 2019 tribe29 GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

# pylint: disable=protected-access


import pytest
from pytest import MonkeyPatch

# No stub file
from tests.testlib.base import Scenario

from cmk.utils.parameters import TimespecificParameters, TimespecificParameterSet
from cmk.utils.tags import TagGroupID, TagID
from cmk.utils.type_defs import (
    CheckPluginName,
    HostName,
    LegacyCheckParameters,
    RuleSetName,
    ServiceID,
)

from cmk.checkers.check_table import ConfiguredService, FilterMode, HostCheckTable
from cmk.checkers.discovery import AutocheckEntry

import cmk.base.api.agent_based.register as agent_based_register
from cmk.base import config
from cmk.base.api.agent_based.checking_classes import CheckPlugin


@pytest.fixture(autouse=True, scope="module")
def _use_fix_register(fix_register):
    """These tests modify the plugin registry. Make sure to load it first."""


def test_cluster_ignores_nodes_parameters(monkeypatch: MonkeyPatch) -> None:
    node = HostName("node")
    cluster = HostName("cluster")

    service_id = ServiceID(CheckPluginName("smart_temp"), "auto-clustered")

    ts = Scenario()
    ts.add_host("node")
    ts.add_cluster("cluster", nodes=["node"])
    ts.set_ruleset(
        "clustered_services",
        [
            {
                "condition": {
                    "service_description": [{"$regex": "Temperature SMART auto-clustered$"}],
                    "host_name": ["node"],
                },
                "value": True,
            }
        ],
    )
    ts.set_autochecks("node", [AutocheckEntry(*service_id, {}, {})])
    config_cache = ts.apply(monkeypatch)

    # a rule for the node:
    monkeypatch.setattr(
        config,
        "_get_configured_parameters",
        lambda host, plugin_name, plugin, item: (
            TimespecificParameters(
                (TimespecificParameterSet.from_parameters({"levels_for_node": (1, 2)}),)
            )
            if host == node
            else TimespecificParameters()
        ),
    )

    clustered_service = config_cache.check_table(cluster)[service_id]
    assert clustered_service.parameters.entries == (
        TimespecificParameterSet.from_parameters({"levels": (35, 40)}),
    )


def test_check_table_enforced_vs_discovered_precedence(monkeypatch):
    smart = CheckPluginName("smart_temp")
    ts = Scenario()
    ts.add_host("node")
    ts.add_cluster("cluster", nodes=["node"])
    ts.set_autochecks(
        "node",
        [
            AutocheckEntry(smart, "cluster-item", {"source": "autochecks"}, {}),
            AutocheckEntry(smart, "cluster-item-overridden", {"source": "autochecks"}, {}),
            AutocheckEntry(smart, "node-item", {"source": "autochecks"}, {}),
        ],
    )
    ts.set_option(
        "static_checks",
        {
            "temperature": [
                {
                    "value": ("smart_temp", "cluster-item", {"source": "enforced-on-node"}),
                    "condition": {"host_name": ["node"]},
                },
                {
                    "value": ("smart_temp", "node-item", {"source": "enforced-on-node"}),
                    "condition": {"host_name": ["node"]},
                },
                {
                    "value": (
                        "smart_temp",
                        "cluster-item-overridden",
                        {"source": "enforced-on-cluster"},
                    ),
                    "condition": {"host_name": ["cluster"]},
                },
            ]
        },
    )
    ts.set_ruleset(
        "clustered_services",
        [
            {
                "condition": {
                    "service_description": [{"$regex": "Temperature SMART cluster"}],
                    "host_name": ["node"],
                },
                "value": True,
            }
        ],
    )
    config_cache = ts.apply(monkeypatch)

    node_services = config_cache.check_table("node")
    cluster_services = config_cache.check_table("cluster")

    assert len(node_services) == 1
    assert len(cluster_services) == 2

    def _source_of_item(table: HostCheckTable, item: str) -> str:
        timespecific_params = table[ServiceID(smart, item)].parameters
        p = timespecific_params.evaluate(lambda _: True)
        assert p is not None
        assert not isinstance(p, (tuple, list, str, int))
        return p["source"]

    assert _source_of_item(node_services, "node-item") == "enforced-on-node"
    assert _source_of_item(cluster_services, "cluster-item") == "enforced-on-node"
    assert _source_of_item(cluster_services, "cluster-item-overridden") == "enforced-on-cluster"


# TODO: This misses a lot of cases
# - different check_table arguments
@pytest.mark.parametrize(
    "hostname_str, filter_mode, expected_result",
    [
        ("empty-host", FilterMode.NONE, {}),
        # Skip the autochecks automatically for ping hosts
        ("ping-host", FilterMode.NONE, {}),
        (
            "no-autochecks",
            FilterMode.NONE,
            {
                (CheckPluginName("smart_temp"), "/dev/sda"): ConfiguredService(
                    check_plugin_name=CheckPluginName("smart_temp"),
                    item="/dev/sda",
                    description="Temperature SMART /dev/sda",
                    parameters=TimespecificParameters(
                        (
                            TimespecificParameterSet({}, ()),
                            TimespecificParameterSet({"levels": (35, 40)}, ()),
                        )
                    ),
                    discovered_parameters={},
                    service_labels={},
                    is_enforced=True,
                ),
            },
        ),
        (
            "ignore-not-existing-checks",
            FilterMode.NONE,
            {
                (CheckPluginName("bla_blub"), "ITEM"): ConfiguredService(
                    check_plugin_name=CheckPluginName("bla_blub"),
                    item="ITEM",
                    description="Unimplemented check bla_blub / ITEM",
                    parameters=TimespecificParameters(()),
                    discovered_parameters={},
                    service_labels={},
                    is_enforced=False,
                ),
                (CheckPluginName("blub_bla"), "ITEM"): ConfiguredService(
                    check_plugin_name=CheckPluginName("blub_bla"),
                    item="ITEM",
                    description="Unimplemented check blub_bla / ITEM",
                    parameters=TimespecificParameters(),
                    discovered_parameters={},
                    service_labels={},
                    is_enforced=True,
                ),
            },
        ),
        (
            "ignore-disabled-rules",
            FilterMode.NONE,
            {
                (CheckPluginName("smart_temp"), "ITEM2"): ConfiguredService(
                    check_plugin_name=CheckPluginName("smart_temp"),
                    item="ITEM2",
                    description="Temperature SMART ITEM2",
                    parameters=TimespecificParameters(
                        (
                            TimespecificParameterSet({}, ()),
                            TimespecificParameterSet({"levels": (35, 40)}, ()),
                        )
                    ),
                    discovered_parameters={},
                    service_labels={},
                    is_enforced=True,
                ),
            },
        ),
        (
            "node1",
            FilterMode.NONE,
            {
                (CheckPluginName("smart_temp"), "auto-not-clustered"): ConfiguredService(
                    check_plugin_name=CheckPluginName("smart_temp"),
                    item="auto-not-clustered",
                    description="Temperature SMART auto-not-clustered",
                    parameters=TimespecificParameters(
                        (TimespecificParameterSet({"levels": (35, 40)}, ()),)
                    ),
                    discovered_parameters={},
                    service_labels={},
                    is_enforced=False,
                ),
                (CheckPluginName("smart_temp"), "static-node1"): ConfiguredService(
                    check_plugin_name=CheckPluginName("smart_temp"),
                    item="static-node1",
                    description="Temperature SMART static-node1",
                    parameters=TimespecificParameters(
                        (
                            TimespecificParameterSet({}, ()),
                            TimespecificParameterSet({"levels": (35, 40)}, ()),
                        )
                    ),
                    discovered_parameters={},
                    service_labels={},
                    is_enforced=True,
                ),
            },
        ),
        (
            "cluster1",
            FilterMode.NONE,
            {
                (CheckPluginName("smart_temp"), "static-cluster"): ConfiguredService(
                    check_plugin_name=CheckPluginName("smart_temp"),
                    item="static-cluster",
                    description="Temperature SMART static-cluster",
                    parameters=TimespecificParameters(
                        (
                            TimespecificParameterSet({}, ()),
                            TimespecificParameterSet({"levels": (35, 40)}, ()),
                        )
                    ),
                    discovered_parameters={},
                    service_labels={},
                    is_enforced=True,
                ),
                (CheckPluginName("smart_temp"), "auto-clustered"): ConfiguredService(
                    check_plugin_name=CheckPluginName("smart_temp"),
                    item="auto-clustered",
                    description="Temperature SMART auto-clustered",
                    parameters=TimespecificParameters(
                        (TimespecificParameterSet({"levels": (35, 40)}, ()),)
                    ),
                    discovered_parameters={},
                    service_labels={},
                    is_enforced=False,
                ),
            },
        ),
        (
            "node2",
            FilterMode.INCLUDE_CLUSTERED,
            {
                (CheckPluginName("smart_temp"), "auto-clustered"): ConfiguredService(
                    check_plugin_name=CheckPluginName("smart_temp"),
                    item="auto-clustered",
                    description="Temperature SMART auto-clustered",
                    parameters=TimespecificParameters(
                        (TimespecificParameterSet({"levels": (35, 40)}, ()),)
                    ),
                    discovered_parameters={},
                    service_labels={},
                    is_enforced=False,
                )
            },
        ),
        (
            "cluster2",
            FilterMode.INCLUDE_CLUSTERED,
            {
                (CheckPluginName("smart_temp"), "auto-clustered"): ConfiguredService(
                    check_plugin_name=CheckPluginName("smart_temp"),
                    item="auto-clustered",
                    description="Temperature SMART auto-clustered",
                    parameters=TimespecificParameters(
                        (TimespecificParameterSet({"levels": (35, 40)}, ()),)
                    ),
                    discovered_parameters={},
                    service_labels={},
                    is_enforced=False,
                )
            },
        ),
        (
            "node3",
            FilterMode.INCLUDE_CLUSTERED,
            {
                (CheckPluginName("smart_temp"), "auto-clustered"): ConfiguredService(
                    check_plugin_name=CheckPluginName("smart_temp"),
                    item="auto-clustered",
                    description="Temperature SMART auto-clustered",
                    parameters=TimespecificParameters(
                        (TimespecificParameterSet({"levels": (35, 40)}, ()),)
                    ),
                    discovered_parameters={},
                    service_labels={},
                    is_enforced=False,
                )
            },
        ),
        (
            "node4",
            FilterMode.INCLUDE_CLUSTERED,
            {},
        ),
    ],
)
def test_check_table(
    monkeypatch: MonkeyPatch,
    hostname_str: str,
    filter_mode: FilterMode,
    expected_result: HostCheckTable,
) -> None:
    hostname = HostName(hostname_str)

    ts = Scenario()
    ts.add_host(hostname, tags={TagGroupID("criticality"): TagID("test")})
    ts.add_host("ping-host", tags={TagGroupID("agent"): TagID("no-agent")})
    ts.add_host("node1")
    ts.add_cluster("cluster1", nodes=["node1"])
    ts.add_host("node2")
    ts.add_host("node3")
    ts.add_host("node4")
    ts.add_cluster("cluster2", nodes=["node2", "node3", "node4"])
    ts.set_option(
        "static_checks",
        {
            "temperature": [
                {
                    "condition": {"host_name": ["no-autochecks", "autocheck-overwrite"]},
                    "value": ("smart.temp", "/dev/sda", {}),
                },
                {
                    "condition": {"host_name": ["ignore-not-existing-checks"]},
                    "value": ("blub.bla", "ITEM", {}),
                },
                {
                    "condition": {"host_name": ["ignore-disabled-rules"]},
                    "options": {"disabled": True},
                    "value": ("smart.temp", "ITEM1", {}),
                },
                {
                    "condition": {"host_name": ["ignore-disabled-rules"]},
                    "value": ("smart.temp", "ITEM2", {}),
                },
                {
                    "condition": {"host_name": ["static-check-overwrite"]},
                    "value": ("smart.temp", "/dev/sda", {"rule": 1}),
                },
                {
                    "condition": {"host_name": ["static-check-overwrite"]},
                    "value": ("smart.temp", "/dev/sda", {"rule": 2}),
                },
                {
                    "condition": {"host_name": ["node1"]},
                    "value": ("smart.temp", "static-node1", {}),
                },
                {
                    "condition": {"host_name": ["cluster1"]},
                    "value": ("smart.temp", "static-cluster", {}),
                },
            ]
        },
    )
    ts.set_ruleset(
        "clustered_services",
        [
            {
                "condition": {
                    "service_description": [{"$regex": "Temperature SMART auto-clustered$"}],
                    "host_name": ["node1", "node2", "node3"],  # no node4 here!
                },
                "value": True,
            }
        ],
    )
    ts.set_autochecks(
        "ping-host",
        [
            AutocheckEntry(CheckPluginName("smart_temp"), "bla", {}, {}),
        ],
    )
    ts.set_autochecks(
        "autocheck-overwrite",
        [
            AutocheckEntry(CheckPluginName("smart_temp"), "/dev/sda", {"is_autocheck": True}, {}),
            AutocheckEntry(CheckPluginName("smart_temp"), "/dev/sdb", {"is_autocheck": True}, {}),
        ],
    )
    ts.set_autochecks(
        "ignore-not-existing-checks",
        [
            AutocheckEntry(CheckPluginName("bla_blub"), "ITEM", {}, {}),
        ],
    )
    ts.set_autochecks(
        "node1",
        [
            AutocheckEntry(CheckPluginName("smart_temp"), "auto-clustered", {}, {}),
            AutocheckEntry(CheckPluginName("smart_temp"), "auto-not-clustered", {}, {}),
        ],
    )
    ts.set_autochecks(
        "node2",
        [
            AutocheckEntry(CheckPluginName("smart_temp"), "auto-clustered", {}, {}),
        ],
    )

    config_cache = ts.apply(monkeypatch)

    assert set(config_cache.check_table(hostname, filter_mode=filter_mode)) == set(expected_result)
    for key, value in config_cache.check_table(hostname, filter_mode=filter_mode).items():
        assert key in expected_result
        assert expected_result[key] == value


@pytest.mark.parametrize(
    "hostname_str, expected_result",
    [
        ("mgmt-board-ipmi", [(CheckPluginName("mgmt_ipmi_sensors"), "TEMP X")]),
        ("ipmi-host", [(CheckPluginName("ipmi_sensors"), "TEMP Y")]),
    ],
)
def test_check_table_of_mgmt_boards(
    monkeypatch: MonkeyPatch, hostname_str: str, expected_result: list[ServiceID]
) -> None:
    hostname = HostName(hostname_str)

    ts = Scenario()
    ts.add_host(
        "mgmt-board-ipmi",
        tags={
            TagGroupID("piggyback"): TagID("auto-piggyback"),
            TagGroupID("networking"): TagID("lan"),
            TagGroupID("address_family"): TagID("no-ip"),
            TagGroupID("criticality"): TagID("prod"),
            TagGroupID("snmp_ds"): TagID("no-snmp"),
            TagGroupID("site"): TagID("heute"),
            TagGroupID("agent"): TagID("no-agent"),
        },
    )
    ts.add_host(
        "ipmi-host",
        tags={
            TagGroupID("piggyback"): TagID("auto-piggyback"),
            TagGroupID("networking"): TagID("lan"),
            TagGroupID("agent"): TagID("cmk-agent"),
            TagGroupID("criticality"): TagID("prod"),
            TagGroupID("snmp_ds"): TagID("no-snmp"),
            TagGroupID("site"): TagID("heute"),
            TagGroupID("address_family"): TagID("ip-v4-only"),
        },
    )
    ts.set_option("management_protocol", {"mgmt-board-ipmi": "ipmi"})

    ts.set_autochecks(
        "mgmt-board-ipmi",
        [AutocheckEntry(CheckPluginName("mgmt_ipmi_sensors"), "TEMP X", {}, {})],
    )
    ts.set_autochecks(
        "ipmi-host",
        [AutocheckEntry(CheckPluginName("ipmi_sensors"), "TEMP Y", {}, {})],
    )

    config_cache = ts.apply(monkeypatch)

    assert list(config_cache.check_table(hostname).keys()) == expected_result


def test_check_table__static_checks_win(monkeypatch: MonkeyPatch) -> None:
    hostname_str = "df_host"
    hostname = HostName(hostname_str)
    plugin_name = CheckPluginName("df")
    item = "/snap/core/9066"

    ts = Scenario()
    ts.add_host(hostname)
    ts.set_option(
        "static_checks",
        {
            "filesystem": [
                {
                    "condition": {"host_name": [hostname_str]},
                    "value": (plugin_name, item, {"source": "static"}),
                }
            ],
        },
    )
    ts.set_autochecks(hostname_str, [AutocheckEntry(plugin_name, item, {"source": "auto"}, {})])

    chk_table = ts.apply(monkeypatch).check_table(hostname)

    # assert check table is populated as expected
    assert len(chk_table) == 1
    # assert static checks won
    effective_params = chk_table[ServiceID(plugin_name, item)].parameters.evaluate(lambda _: True)
    assert effective_params["source"] == "static"  # type: ignore[index,call-overload]


@pytest.mark.parametrize(
    "check_group_parameters",
    [
        {},
        {
            "levels": (4, 5, 6, 7),
        },
    ],
)
def test_check_table__get_static_check_entries(
    monkeypatch: MonkeyPatch, check_group_parameters: LegacyCheckParameters
) -> None:
    hostname = HostName("hostname")

    static_parameters_default = {"levels": (1, 2, 3, 4)}
    static_checks: dict[str, list] = {
        "ps": [
            {
                "condition": {"service_description": [], "host_name": [hostname]},
                "options": {},
                "value": ("ps", "item", static_parameters_default),
            }
        ],
    }

    ts = Scenario()
    ts.add_host(hostname)
    ts.set_option("static_checks", static_checks)

    ts.set_ruleset(
        "checkgroup_parameters",
        {
            "ps": [
                {
                    "condition": {"service_description": [], "host_name": [hostname]},
                    "options": {},
                    "value": check_group_parameters,
                }
            ],
        },
    )

    config_cache = ts.apply(monkeypatch)

    monkeypatch.setattr(
        agent_based_register,
        "get_check_plugin",
        lambda cpn: CheckPlugin(
            CheckPluginName("ps"),
            [],
            "Process item",
            lambda: [],
            None,
            None,
            "merged",
            lambda: [],
            {},
            RuleSetName("ps"),
            None,
            None,
        ),
    )

    static_check_parameters = [
        service.parameters for service in config._get_enforced_services(config_cache, hostname)
    ]

    entries = config._get_checkgroup_parameters(
        config_cache,
        hostname,
        "ps",
        "item",
        "Process item",
    )

    assert len(entries) == 1
    assert entries[0] == check_group_parameters

    assert len(static_check_parameters) == 1
    static_check_parameter = static_check_parameters[0]
    assert static_check_parameter == TimespecificParameters(
        (
            TimespecificParameterSet(static_parameters_default, ()),
            TimespecificParameterSet({}, ()),
        )
    )
