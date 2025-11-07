import time
from typing import Dict, List, Optional
import os
import json

import psutil
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import Header

from ros_process_monitor.msg import ProcessUsage, ProcessUsageArray

def make_header(node: Node) -> Header:
    h = Header()
    h.stamp = node.get_clock().now().to_msg()
    h.frame_id = ''
    return h


class ProcessMonitor(Node):
    def __init__(self) -> None:
        super().__init__('process_monitor_node')

        self.declare_parameter('process_names', [''])
        self.declare_parameter('publish_topic', 'process_usage')
        self.declare_parameter('publish_interval_sec', 2.0)
        self.declare_parameter('config_file', '')  # optional path to JSON config

        # Determine config path: param > default in package share
        cfg_param = self.get_parameter('config_file').get_parameter_value().string_value
        if cfg_param:
            self._config_path = cfg_param
        else:
            try:
                from ament_index_python.packages import get_package_share_directory
                share_dir = get_package_share_directory('ros_process_monitor')
                self._config_path = os.path.join(share_dir, 'config', 'process_config.json')
            except Exception:
                self._config_path = ''
        self._config_mtime: Optional[float] = None

        self.process_names: List[str] = self.get_parameter('process_names').get_parameter_value().string_array_value
        self.publish_topic: str = self.get_parameter('publish_topic').get_parameter_value().string_value
        self.publish_interval: float = self.get_parameter('publish_interval_sec').get_parameter_value().double_value

        # If config file provided, load settings from there (override parameters)
        if self._config_path:
            self._load_config(initial=True)

        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self.publisher = self.create_publisher(ProcessUsageArray, self.publish_topic, qos)

        # Cache mapping from PID to psutil.Process
        self.pid_cache: Dict[int, psutil.Process] = {}

        # Prime cpu_percent for processes to avoid initial 0.0 values
        self._prime_cpu_percent()

        # Start periodic timer
        self.timer = self.create_timer(self.publish_interval, self._on_timer)

    def _prime_cpu_percent(self) -> None:
        # Iterate once to initialize cpu_percent internal sampling
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                _ = proc.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def _collect_usage(self) -> ProcessUsageArray:
        # Aggregate by process name across multiple PIDs
        aggregate: Dict[str, Dict[str, float]] = {}

        tracked_names = set(self.process_names)

        for proc in psutil.process_iter(['pid', 'name']):
            try:
                name = proc.info.get('name') or ''
                if name not in tracked_names:
                    continue

                cpu = proc.cpu_percent(interval=None)  # Non-blocking; meaningful after priming
                mem_percent = proc.memory_percent()
                mem_info = proc.memory_info()

                entry = aggregate.setdefault(name, {
                    'cpu': 0.0,
                    'mem_percent': 0.0,
                    'rss': 0.0,
                    'vms': 0.0,
                })
                entry['cpu'] += float(cpu)
                entry['mem_percent'] += float(mem_percent)
                entry['rss'] += float(mem_info.rss)
                entry['vms'] += float(mem_info.vms)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        msg = ProcessUsageArray()
        msg.header = make_header(self)
        total_cpu = 0.0
        total_mem = 0.0
        for name in self.process_names:
            if name not in aggregate:
                # Include names with zeroes so downstream knows it's tracked
                pu = ProcessUsage()
                pu.header = msg.header
                pu.name = name
                pu.cpu_percent = 0.0
                pu.mem_percent = 0.0
                pu.rss_bytes = 0
                pu.vms_bytes = 0
                msg.processes.append(pu)
                continue
            data = aggregate[name]
            pu = ProcessUsage()
            pu.header = msg.header
            pu.name = name
            pu.cpu_percent = float(data['cpu'])
            pu.mem_percent = float(data['mem_percent'])
            pu.rss_bytes = int(data['rss'])
            pu.vms_bytes = int(data['vms'])
            msg.processes.append(pu)
            total_cpu += pu.cpu_percent
            total_mem += pu.mem_percent

        msg.total_cpu_percent = float(total_cpu)
        msg.total_mem_percent = float(total_mem)
        return msg

    def _on_timer(self) -> None:
        try:
            # If using config file, hot-reload when mtime changes
            if self._config_path:
                self._load_config(initial=False)
            msg = self._collect_usage()
            self.publisher.publish(msg)
        except Exception as exc:
            self.get_logger().error(f'Failed to publish process usage: {exc}')

    def _load_config(self, initial: bool) -> None:
        path = self._config_path
        try:
            st = os.stat(path)
        except FileNotFoundError:
            if initial:
                self.get_logger().warn(f'config_file not found: {path}; using node parameters')
            return

        mtime = st.st_mtime
        if self._config_mtime is not None and mtime == self._config_mtime:
            return  # unchanged

        try:
            with open(path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        except Exception as e:
            self.get_logger().error(f'Failed to read config_file {path}: {e}')
            return

        # Update process_names
        names_in = cfg.get('process_names', [])
        if isinstance(names_in, list):
            # Deduplicate while preserving order
            seen = set()
            ordered: List[str] = []
            for n in names_in:
                if isinstance(n, str) and n and n not in seen:
                    ordered.append(n)
                    seen.add(n)
            if ordered:
                self.process_names = ordered

        # Update publish_topic (recreate publisher if changed)
        topic_in = cfg.get('publish_topic')
        if isinstance(topic_in, str) and topic_in and topic_in != self.publish_topic:
            self.publish_topic = topic_in
            qos = QoSProfile(
                reliability=ReliabilityPolicy.RELIABLE,
                history=HistoryPolicy.KEEP_LAST,
                depth=10,
            )
            self.publisher = self.create_publisher(ProcessUsageArray, self.publish_topic, qos)
            self.get_logger().info(f'Publisher moved to topic {self.publish_topic}')

        # Update publish interval (recreate timer if changed significantly)
        interval_in = cfg.get('publish_interval_sec')
        if isinstance(interval_in, (int, float)) and interval_in > 0:
            if abs(float(interval_in) - float(self.publish_interval)) > 1e-6:
                self.publish_interval = float(interval_in)
                # cancel old timer and create new
                try:
                    self.destroy_timer(self.timer)
                except Exception:
                    pass
                self.timer = self.create_timer(self.publish_interval, self._on_timer)
                self.get_logger().info(f'Timer interval updated to {self.publish_interval}s')

        self._config_mtime = mtime
        self.get_logger().info(f'Loaded config from {path}')


def main() -> None:
    rclpy.init()
    node = ProcessMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


