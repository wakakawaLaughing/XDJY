#!/usr/bin/env python3
"""
固定频率 Header 发布脚本
- 以固定频率(默认 60Hz)在指定话题发布 std_msgs/msg/Header
- 仅赋值 header.stamp=当前时间，用于测试纯网络延迟(接收端用 接收时间-消息时间戳)

运行示例:
  python3 monitor/latency_header_publisher.py -h
  python3 monitor/latency_header_publisher.py --ros-args \
    -p topic:=/latency_test/header -p hz:=60 -p reliability:=reliable -p frame_id:=test
"""

import sys
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from std_msgs.msg import Header


class LatencyHeaderPublisher(Node):
    def __init__(self):
        super().__init__('latency_header_publisher')

        # 参数
        self.declare_parameter('topic', '/latency_test/header')
        self.declare_parameter('hz', 60)
        self.declare_parameter('reliability', 'reliable')  # reliable | best_effort
        self.declare_parameter('frame_id', '')

        topic = self.get_parameter('topic').get_parameter_value().string_value
        hz = int(self.get_parameter('hz').get_parameter_value().integer_value)
        reliability = (self.get_parameter('reliability').get_parameter_value().string_value or 'reliable').lower()
        self.frame_id = self.get_parameter('frame_id').get_parameter_value().string_value

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

        self.pub = self.create_publisher(Header, topic, qos)

        # 定时器
        self.period = 1.0 / max(1, hz)
        self.timer = self.create_timer(self.period, self._on_tick)
        self.seq = 0

        self.get_logger().info(
            f"Latency header publisher started: topic='{topic}', hz={hz}, reliability={qos.reliability}"
        )

    def _on_tick(self):
        # 构造 Header，仅填充 stamp(可选 frame_id)
        h = Header()
        h.stamp = self.get_clock().now().to_msg()
        h.frame_id = self.frame_id
        # 注意: Header.seq 在 ROS2 中未使用，保留计数仅作辅助
        self.pub.publish(h)
        self.seq += 1


def main(args=None):
    def print_usage():
        print(
            """
用法:
  python3 monitor/latency_header_publisher.py [-h]
  python3 monitor/latency_header_publisher.py --ros-args \
    -p topic:=/latency_test/header -p hz:=60 -p reliability:=reliable|best_effort -p frame_id:=test

参数(ROS 参数传入):
  topic        : 发布话题，默认 /latency_test/header
  hz           : 频率Hz，默认 60
  reliability  : reliable | best_effort，默认 reliable
  frame_id     : 可选 frame_id，默认空
""".strip()
        )

    if args is None:
        args = sys.argv
    if any(a in ("-h", "--help") for a in args[1:]):
        print_usage()
        return

    rclpy.init(args=args)
    node = LatencyHeaderPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()


