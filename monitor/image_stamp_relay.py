#!/usr/bin/env python3
"""
ROS2 图像时间戳中转脚本
- 订阅三个图像话题，接收到后把 header.stamp 改为当前时间（发送瞬间）并转发
- 默认话题：
  - 输入：/camera/camera/color/image_raw, /cam_left/image_raw, /cam_right/image_raw
  - 输出：/camera/color/image_sent, /cam_left/image_sent, /cam_right/image_sent
"""

import rclpy
from rclpy.node import Node
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from sensor_msgs.msg import Image


class ImageStampRelay(Node):
    def __init__(self):
        super().__init__('image_stamp_relay')

        # 声明/读取参数（允许外部覆盖）
        self.declare_parameter('front_in', '/camera/camera/color/image_raw')
        self.declare_parameter('left_in', '/cam_left/image_raw')
        self.declare_parameter('right_in', '/cam_right/image_raw')
        self.declare_parameter('front_out', '/camera/color/image_sent')
        self.declare_parameter('left_out', '/cam_left/image_sent')
        self.declare_parameter('right_out', '/cam_right/image_sent')

        self.front_in = self.get_parameter('front_in').get_parameter_value().string_value
        self.left_in = self.get_parameter('left_in').get_parameter_value().string_value
        self.right_in = self.get_parameter('right_in').get_parameter_value().string_value
        self.front_out = self.get_parameter('front_out').get_parameter_value().string_value
        self.left_out = self.get_parameter('left_out').get_parameter_value().string_value
        self.right_out = self.get_parameter('right_out').get_parameter_value().string_value

        # QoS：左右为 BEST_EFFORT，前视为 RELIABLE（可与实际发布端匹配）
        qos_left_right = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            durability=DurabilityPolicy.VOLATILE,
        )
        qos_front = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            durability=DurabilityPolicy.VOLATILE,
        )

        # 发布者
        self.front_pub = self.create_publisher(Image, self.front_out, qos_front)
        self.left_pub = self.create_publisher(Image, self.left_out, qos_left_right)
        self.right_pub = self.create_publisher(Image, self.right_out, qos_left_right)

        # 为每个订阅创建独立的回调组，配合多线程执行器实现并行处理
        front_cb_group = MutuallyExclusiveCallbackGroup()
        left_cb_group = MutuallyExclusiveCallbackGroup()
        right_cb_group = MutuallyExclusiveCallbackGroup()
        
        # 订阅者
        self.front_sub = self.create_subscription(Image, self.front_in, self._front_cb, qos_front, callback_group=front_cb_group)
        self.left_sub = self.create_subscription(Image, self.left_in, self._left_cb, qos_left_right, callback_group=left_cb_group)
        self.right_sub = self.create_subscription(Image, self.right_in, self._right_cb, qos_left_right, callback_group=right_cb_group)

        self.get_logger().info(
            f"Stamp relay: \n"
            f"  front: '{self.front_in}' -> '{self.front_out}'\n"
            f"  left : '{self.left_in}' -> '{self.left_out}'\n"
            f"  right: '{self.right_in}' -> '{self.right_out}'"
        )
        
        # 统计转发计数
        self.frame_counts = {
            'front': 0,
            'left': 0,
            'right': 0,
        }

    def _stamp_and_pub(self, msg: Image, pub, topic_name: str):
        # 修改为发送瞬间的时间戳
        send_time = self.get_clock().now()
        msg.header.stamp = send_time.to_msg()

        # 发布前打印原始图像大小
        try:
            raw_size_bytes = len(msg.data)
        except Exception:
            raw_size_bytes = 0
        self.get_logger().info(f"{topic_name}: publish size_raw={raw_size_bytes/1024.0:.2f}KB")

        pub.publish(msg)
        
        # 打印转发信息
        self.frame_counts[topic_name] += 1
        stamp_ms = send_time.nanoseconds / 1_000_000.0
        self.get_logger().info(f'{topic_name}: 转发消息 (时间戳: {stamp_ms:.3f}ms, 计数: {self.frame_counts[topic_name]})')

    def _front_cb(self, msg: Image):
        self._stamp_and_pub(msg, self.front_pub, 'front')

    def _left_cb(self, msg: Image):
        self._stamp_and_pub(msg, self.left_pub, 'left')

    def _right_cb(self, msg: Image):
        self._stamp_and_pub(msg, self.right_pub, 'right')


def main(args=None):
    rclpy.init(args=args)
    node = ImageStampRelay()
    
    # 使用多线程执行器，让回调可以并行执行，避免阻塞其他订阅者
    from rclpy.executors import MultiThreadedExecutor
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()


