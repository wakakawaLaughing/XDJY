#!/usr/bin/env python3
"""
ROS2 图像监控脚本
实时接收三个图像话题，保存到 bag 文件，并监控时间戳差异
"""

import rclpy
from rclpy.node import Node
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from sensor_msgs.msg import Image
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
import rosbag2_py
from rclpy.serialization import serialize_message
import time
from datetime import datetime
import os
from collections import defaultdict


class ImageMonitor(Node):
    def __init__(self):
        super().__init__('image_monitor')
        
        # 参数：运行时长（秒），统计模式（header | network）
        self.declare_parameter('run_seconds', 10 * 60)
        self.declare_parameter('stat_mode', 'header')  # header 或 network
        self.run_seconds = int(self.get_parameter('run_seconds').get_parameter_value().integer_value)
        self.stat_mode = self.get_parameter('stat_mode').get_parameter_value().string_value or 'header'

        # 根据统计模式选择话题
        if self.stat_mode == 'network':
            # network 模式：订阅转发后的话题（带 _sent 后缀）
            self.topic_configs = {
                '/camera/color/image_sent': (19.0, 60),  # 前视，60Hz，阈值19ms
                '/cam_left/image_sent': (35.0, 30),       # 左视，30Hz，阈值35ms
                '/cam_right/image_sent': (35.0, 30),      # 右视，30Hz，阈值35ms
            }
        else:
            # header 模式：订阅原始话题
            self.topic_configs = {
                '/camera/camera/color/image_raw': (19.0, 60),  # 前视，60Hz，阈值19ms
                '/cam_left/image_raw': (35.0, 30),              # 左视，30Hz，阈值35ms
                '/cam_right/image_raw': (35.0, 30),             # 右视，30Hz，阈值35ms
            }
        
        # 网络延迟阈值配置（默认 3ms）
        self.network_thresholds = {topic: 3.0 for topic in self.topic_configs.keys()}
        
        # 存储每个话题的最后一帧的消息头时间戳（纳秒）与接收时间戳（纳秒）
        self.last_header_ts_ns = {}
        self.last_recv_ts_ns = {}
        
        # 统计信息
        self.frame_counts = defaultdict(int)
        # 统计各话题的间隔/延时（毫秒）：消息头时间间隔、接收时间间隔、网络延时（接收-消息时间）
        self.header_intervals_ms = defaultdict(list)
        self.recv_intervals_ms = defaultdict(list)
        self.network_latency_ms = defaultdict(list)
        # 控制台打印节流（每个话题最短打印间隔，单位：纳秒）
        self.console_log_interval_ns = 200_000_000  # 200ms
        self.last_console_log_time_ns = {}

        # 自动停止定时器
        self.stop_timer = self.create_timer(float(self.run_seconds), self._on_timeout)
        
        # 创建日志目录
        self.log_dir = os.path.join(os.path.dirname(__file__), 'logs')
        os.makedirs(self.log_dir, exist_ok=True)
        
        # 订阅所有话题（不需要存储订阅对象，ROS2 会自动管理）
        # 为左右摄像头使用 BEST_EFFORT，前视使用兼容的 QoS
        # 为每个订阅创建独立的回调组，配合多线程执行器实现并行处理
        for topic_name, (threshold_ms, freq_hz) in self.topic_configs.items():
            # 为每个订阅创建独立的回调组，确保回调可以在不同线程执行
            callback_group = MutuallyExclusiveCallbackGroup()
            
            # 左右摄像头使用 BEST_EFFORT reliability，前视使用兼容的 QoS
            if '/cam_left' in topic_name or '/cam_right' in topic_name:
                # 左右摄像头：使用 BEST_EFFORT reliability
                qos_profile = QoSProfile(
                    reliability=ReliabilityPolicy.BEST_EFFORT,
                    history=HistoryPolicy.KEEP_LAST,
                    depth=10,
                    durability=DurabilityPolicy.VOLATILE
                )
            else:
                # 前视摄像头：使用 RELIABLE reliability（默认，因为已经正常工作）
                qos_profile = QoSProfile(
                    reliability=ReliabilityPolicy.RELIABLE,
                    history=HistoryPolicy.KEEP_LAST,
                    depth=10,
                    durability=DurabilityPolicy.VOLATILE
                )
            
            self.create_subscription(
                Image,
                topic_name,
                lambda msg, t=topic_name: self.image_callback(msg, t),
                qos_profile,
                callback_group=callback_group
            )
            self.get_logger().info(f'订阅话题: {topic_name} (阈值: {threshold_ms}ms, 频率: {freq_hz}Hz, QoS: {qos_profile.reliability})')
        
        
    def image_callback(self, msg, topic_name):
        """图像消息回调函数"""
        # 输出消息头中的时间戳（精确到毫秒）
        msg_timestamp_sec = msg.header.stamp.sec
        msg_timestamp_nsec = msg.header.stamp.nanosec
        msg_timestamp_ms = msg_timestamp_sec * 1000.0 + msg_timestamp_nsec / 1_000_000.0
        
        # 原始图像数据大小（未序列化，字节数）
        try:
            raw_size_bytes = len(msg.data)
        except Exception:
            raw_size_bytes = 0
        
        # 获取回调实际接收到消息的时间戳（纳秒）
        receive_time = self.get_clock().now()
        current_timestamp_ns = receive_time.nanoseconds
        current_timestamp_ms = current_timestamp_ns / 1_000_000.0
        
        # 同时输出到终端（节流）
        log_msg = f'{topic_name} {msg_timestamp_ms:.3f}ms'
        self.get_logger().info(log_msg)
        
        # 更新统计
        self.frame_counts[topic_name] += 1
        
        # 计算序列化后大小（字节），并打印大小与压缩比
        try:
            # 序列化消息
            serialized_msg = serialize_message(msg)
            # 使用消息头中的时间戳（这是数据本身的时间戳）
            msg_timestamp_ns = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
            serialized_size_bytes = len(serialized_msg)
            if raw_size_bytes > 0:
                ratio = serialized_size_bytes / float(raw_size_bytes)
                self.get_logger().info(
                    f'{topic_name} size_raw={raw_size_bytes/1024.0:.2f}KB size_ser={serialized_size_bytes/1024.0:.2f}KB ratio={ratio:.3f}'
                )
            else:
                self.get_logger().info(
                    f'{topic_name} size_raw=0KB size_ser={serialized_size_bytes/1024.0:.2f}KB ratio=NA'
                )
        except Exception as e:
            self.get_logger().error(f'写入 bag 文件失败: {e}')
        
        # 检查消息头时间戳差异（用于监控帧时间间隔抖动）
        if topic_name in self.last_header_ts_ns:
            last_msg_ts = self.last_header_ts_ns[topic_name]
            diff_ns = msg_timestamp_ns - last_msg_ts
            diff_ms = diff_ns / 1_000_000.0  # 转换为毫秒
            if diff_ms >= 0:
                self.header_intervals_ms[topic_name].append(diff_ms)
            
            threshold_ms, freq_hz = self.topic_configs[topic_name]
            # 根据模式做超阈值告警
            if self.stat_mode == 'header':
                if diff_ms > threshold_ms:
                    wall_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    log_msg = (
                        f"[{wall_time}] 话题: {topic_name} | "
                        f"消息间隔: {diff_ms:.2f}ms (阈值: {threshold_ms}ms) | "
                        f"消息时间戳: {msg.header.stamp.sec}.{msg.header.stamp.nanosec:09d} | "
                        f"帧计数: {self.frame_counts[topic_name]}\n"
                    )
                    self.get_logger().warn(
                        f'⚠️  {topic_name}: 消息间隔 {diff_ms:.2f}ms > 阈值 {threshold_ms}ms '
                        f'(帧计数: {self.frame_counts[topic_name]})'
                    )
        
        # 计算接收时间间隔
        if topic_name in self.last_recv_ts_ns:
            recv_diff_ns = current_timestamp_ns - self.last_recv_ts_ns[topic_name]
            recv_diff_ms = recv_diff_ns / 1_000_000.0
            if recv_diff_ms >= 0:
                self.recv_intervals_ms[topic_name].append(recv_diff_ms)

        # 记录网络延时（接收-消息头时间）
        latency_ms = (current_timestamp_ns - msg_timestamp_ns) / 1_000_000.0
        if latency_ms >= 0:
            self.network_latency_ms[topic_name].append(latency_ms)
            # 仅在 network 模式下进行网络延时告警输出
            if self.stat_mode == 'network':
                network_threshold = self.network_thresholds.get(topic_name, 3.0)
                if latency_ms > network_threshold:
                    self.get_logger().warn(
                        f'⚠️  {topic_name}: 网络延时 {latency_ms:.2f}ms > 阈值 {network_threshold}ms '
                        f'(帧计数: {self.frame_counts[topic_name]})'
                    )

        # 更新该话题最后一帧的消息头时间戳与接收时间戳
        self.last_header_ts_ns[topic_name] = msg_timestamp_ns
        self.last_recv_ts_ns[topic_name] = current_timestamp_ns

    def _percentiles(self, arr):
        if not arr:
            return None
        data = sorted(arr)
        n = len(data)
        def pct(p):
            if n == 1:
                return data[0]
            k = p * (n - 1)
            f = int(k)
            c = min(f + 1, n - 1)
            if f == c:
                return data[f]
            return data[f] + (data[c] - data[f]) * (k - f)
        return {
            'min': data[0],
            'p50': pct(0.50),
            'p95': pct(0.95),
            'p99': pct(0.99),
            'max': data[-1],
            'avg': sum(data) / n,
            'cnt': n,
        }

    def _print_summary_table(self):
        # 打印各话题 header 间隔与接收间隔的统计表
        header = (
            "\n================================= 统计汇总 =================================\n"
            "Topic                                   Type      Cnt    Min     P50     P95     P99     Max     Avg   ExCnt   ExPct\n"
            "----------------------------------------------------------------------------------------------"
        )
        print(header)
        def fmt_row(topic, typ, stats):
            if not stats:
                return f"{topic:<40} {typ:<8}    0    -       -       -       -       -       -       0     0.00%"
            # 依据该 topic 的阈值统计超阈值次数与比例
            if typ == 'header':
                threshold_ms = self.topic_configs.get(topic, (0.0, 0))[0]
                series = self.header_intervals_ms.get(topic, [])
            elif typ == 'recv':
                threshold_ms = self.topic_configs.get(topic, (0.0, 0))[0]
                series = self.recv_intervals_ms.get(topic, [])
            else:  # network
                threshold_ms = self.network_thresholds.get(topic, 3.0)
                series = self.network_latency_ms.get(topic, [])
            exceed_cnt = sum(1 for v in series if v > threshold_ms)
            pct = (exceed_cnt / float(max(1, int(stats['cnt'])))) * 100.0
            return (
                f"{topic:<40} {typ:<8} {int(stats['cnt']):>5}  "
                f"{stats['min']:>7.2f} {stats['p50']:>7.2f} {stats['p95']:>7.2f} "
                f"{stats['p99']:>7.2f} {stats['max']:>7.2f} {stats['avg']:>7.2f}  "
                f"{exceed_cnt:>5}  {pct:>6.2f}%"
            )
        for topic in self.topic_configs.keys():
            if self.stat_mode == 'network':
                n_stats = self._percentiles(self.network_latency_ms.get(topic, []))
                print(fmt_row(topic, 'network', n_stats))
            else:
                h_stats = self._percentiles(self.header_intervals_ms.get(topic, []))
                r_stats = self._percentiles(self.recv_intervals_ms.get(topic, []))
                print(fmt_row(topic, 'header', h_stats))
                print(fmt_row(topic, 'recv',   r_stats))
        print("==============================================================================================\n")

    def _on_timeout(self):
        # 停止回调，打印统计并关闭节点
        try:
            self._print_summary_table()
        except Exception as e:
            self.get_logger().error(f'打印统计失败: {e}')
        # 请求关闭
        rclpy.shutdown()
        
    def destroy_node(self):
        
        # 打印统计信息
        self.get_logger().info('=' * 60)
        self.get_logger().info('统计信息:')
        for topic_name, count in self.frame_counts.items():
            threshold_ms, freq_hz = self.topic_configs[topic_name]
            self.get_logger().info(f'  {topic_name}: {count} 帧 (阈值: {threshold_ms}ms)')
        self.get_logger().info('=' * 60)
        
        super().destroy_node()


def main(args=None):
    import sys
    def print_usage():
        print(
            """
用法:
  直接运行脚本:
    python3 monitor/image_monitor.py [-h]

  带参数运行(通过 ROS 参数传入):
    python3 monitor/image_monitor.py --ros-args -p run_seconds:=600 -p stat_mode:=header|network

参数说明(ROS 参数):
  run_seconds  : 运行时长(秒), 默认 600
  stat_mode    : 统计模式, 'header' 或 'network', 默认 'header'

说明:
  - header 模式: 统计相邻帧的 header 时间间隔(以及接收间隔), 并按阈值告警
  - network 模式: 统计网络延时(接收时间 - 消息 header 时间), 并按阈值告警
""".strip()
        )

    if args is None:
        args = sys.argv
    if any(a in ("-h", "--help") for a in args[1:]):
        print_usage()
        return

    rclpy.init(args=args)
    
    node = ImageMonitor()
    
    # 使用多线程执行器，让不同订阅者的回调可以并行执行，避免互相阻塞
    from rclpy.executors import MultiThreadedExecutor
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    
    try:
        executor.spin()
    except KeyboardInterrupt:
        node.get_logger().info('接收到中断信号，正在关闭...')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

