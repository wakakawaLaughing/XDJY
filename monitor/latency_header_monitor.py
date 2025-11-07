#!/usr/bin/env python3
"""
固定 Header 接收统计脚本
- 订阅单个 std_msgs/msg/Header 话题，用于统计：
  1) header 相邻帧间隔(ms)
  2) 接收相邻帧间隔(ms)
  3) 网络延时(ms) = 接收时间 - header.stamp
- 支持运行时间(run_seconds)与统计模式(stat_mode=header|network)参数；默认统计 header

使用示例：
  python3 monitor/latency_header_monitor.py -h
  python3 monitor/latency_header_monitor.py --ros-args \
    -p topic:=/latency_test/header -p run_seconds:=120 -p stat_mode:=network \
    -p reliability:=reliable -p header_threshold_ms:=16.7 -p network_threshold_ms:=3.0
"""

import sys
import rclpy
from rclpy.node import Node
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from std_msgs.msg import Header
from datetime import datetime
from collections import defaultdict


class LatencyHeaderMonitor(Node):
    def __init__(self):
        super().__init__('latency_header_monitor')

        # 参数
        self.declare_parameter('topic', '/latency_test/header')
        self.declare_parameter('run_seconds', 10 * 60)
        self.declare_parameter('stat_mode', 'header')  # header | network
        self.declare_parameter('reliability', 'reliable')  # reliable | best_effort
        self.declare_parameter('header_threshold_ms', 16.7)
        self.declare_parameter('network_threshold_ms', 3.0)

        self.topic = self.get_parameter('topic').get_parameter_value().string_value
        self.run_seconds = int(self.get_parameter('run_seconds').get_parameter_value().integer_value)
        self.stat_mode = (self.get_parameter('stat_mode').get_parameter_value().string_value or 'header')
        reliability = (self.get_parameter('reliability').get_parameter_value().string_value or 'reliable').lower()
        self.header_threshold_ms = float(self.get_parameter('header_threshold_ms').get_parameter_value().double_value)
        self.network_threshold_ms = float(self.get_parameter('network_threshold_ms').get_parameter_value().double_value)

        # QoS
        if reliability == 'best_effort':
            qos = QoSProfile(
                reliability=ReliabilityPolicy.BEST_EFFORT,
                history=HistoryPolicy.KEEP_LAST,
                depth=10,
                durability=DurabilityPolicy.VOLATILE,
            )
        else:
            qos = QoSProfile(
                reliability=ReliabilityPolicy.RELIABLE,
                history=HistoryPolicy.KEEP_LAST,
                depth=10,
                durability=DurabilityPolicy.VOLATILE,
            )

        # 统计存储
        self.frame_count = 0
        self.last_header_ns = None
        self.last_recv_ns = None
        self.header_intervals_ms = []
        self.recv_intervals_ms = []
        self.network_latency_ms = []

        # 订阅（独立回调组）
        cbg = MutuallyExclusiveCallbackGroup()
        self.create_subscription(Header, self.topic, self._cb, qos, callback_group=cbg)

        # 自动停止
        self.create_timer(float(self.run_seconds), self._on_timeout)

        self.get_logger().info(
            f"Latency header monitor started: topic='{self.topic}', run_seconds={self.run_seconds}, "
            f"mode={self.stat_mode}, reliability={qos.reliability}, "
            f"header_thr={self.header_threshold_ms}ms, net_thr={self.network_threshold_ms}ms"
        )

    def _cb(self, msg: Header):
        # 接收时间
        now = self.get_clock().now()
        recv_ns = now.nanoseconds

        # 消息时间
        header_ns = msg.stamp.sec * 1_000_000_000 + msg.stamp.nanosec

        # 打印简要到终端（可按需节流，这里保持每帧）
        msg_ms = header_ns / 1_000_000.0
        self.get_logger().info(f"{self.topic} {msg_ms:.3f}ms")

        # 帧计数
        self.frame_count += 1

        # header 间隔
        if self.last_header_ns is not None:
            diff_ms = (header_ns - self.last_header_ns) / 1_000_000.0
            if diff_ms >= 0:
                self.header_intervals_ms.append(diff_ms)
                if self.stat_mode == 'header' and diff_ms > self.header_threshold_ms:
                    wall = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    self.get_logger().warn(
                        f"⚠️  {self.topic}: header间隔 {diff_ms:.2f}ms > 阈值 {self.header_threshold_ms}ms (帧计数: {self.frame_count})"
                    )

        # 接收间隔
        if self.last_recv_ns is not None:
            rdiff_ms = (recv_ns - self.last_recv_ns) / 1_000_000.0
            if rdiff_ms >= 0:
                self.recv_intervals_ms.append(rdiff_ms)

        # 网络延时
        latency_ms = (recv_ns - header_ns) / 1_000_000.0
        if latency_ms >= 0:
            self.network_latency_ms.append(latency_ms)
            if latency_ms > self.network_threshold_ms:
                self.get_logger().warn(
                    f"⚠️  {self.topic}: 网络延时 {latency_ms:.2f}ms > 阈值 {self.network_threshold_ms}ms (帧计数: {self.frame_count})"
                )

        # 更新 last
        self.last_header_ns = header_ns
        self.last_recv_ns = recv_ns

    def _percentiles(self, data):
        if not data:
            return None
        arr = sorted(data)
        n = len(arr)
        def pct(p):
            if n == 1:
                return arr[0]
            k = p * (n - 1)
            f = int(k)
            c = min(f + 1, n - 1)
            if f == c:
                return arr[f]
            return arr[f] + (arr[c] - arr[f]) * (k - f)
        return {
            'min': arr[0],
            'p50': pct(0.50),
            'p95': pct(0.95),
            'p99': pct(0.99),
            'max': arr[-1],
            'avg': sum(arr) / n,
            'cnt': n,
        }

    def _print_table(self):
        header = (
            "\n================================= 统计汇总 =================================\n"
            "Metric                                  Cnt    Min     P50     P95     P99     Max     Avg   ExCnt   ExPct\n"
            "----------------------------------------------------------------------------------------------"
        )
        print(header)

        def fmt_row(name, stats, threshold):
            if not stats:
                return f"{name:<40}    0    -       -       -       -       -       -       0     0.00%"
            series_map = {
                'header': self.header_intervals_ms,
                'recv': self.recv_intervals_ms,
                'network': self.network_latency_ms,
            }
            series = series_map[name]
            exceed = sum(1 for v in series if v > threshold)
            pct = (exceed / float(max(1, int(stats['cnt'])))) * 100.0
            return (
                f"{name:<40} {int(stats['cnt']):>5}  "
                f"{stats['min']:>7.2f} {stats['p50']:>7.2f} {stats['p95']:>7.2f} "
                f"{stats['p99']:>7.2f} {stats['max']:>7.2f} {stats['avg']:>7.2f}  "
                f"{exceed:>5}  {pct:>6.2f}%"
            )

        h_stats = self._percentiles(self.header_intervals_ms)
        r_stats = self._percentiles(self.recv_intervals_ms)
        n_stats = self._percentiles(self.network_latency_ms)

        if self.stat_mode == 'network':
            print(fmt_row('network', n_stats, self.network_threshold_ms))
        else:
            print(fmt_row('header', h_stats, self.header_threshold_ms))
            print(fmt_row('recv',   r_stats, self.header_threshold_ms))
        print("==============================================================================================\n")

    def _on_timeout(self):
        try:
            self._print_table()
        except Exception as e:
            self.get_logger().error(f'打印统计失败: {e}')
        rclpy.shutdown()


def main(args=None):
    def print_usage():
        print(
            """
用法:
  python3 monitor/latency_header_monitor.py [-h]
  python3 monitor/latency_header_monitor.py --ros-args \
    -p topic:=/latency_test/header -p run_seconds:=600 -p stat_mode:=header|network \
    -p reliability:=reliable|best_effort -p header_threshold_ms:=16.7 -p network_threshold_ms:=3.0
""".strip()
        )

    if args is None:
        args = sys.argv
    if any(a in ("-h", "--help") for a in args[1:]):
        print_usage()
        return

    rclpy.init(args=args)
    node = LatencyHeaderMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()


