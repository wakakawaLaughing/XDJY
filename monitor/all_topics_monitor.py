#!/usr/bin/env python3
"""
ROS2 全话题监控脚本
- 自动发现并订阅所有 ROS2 话题
- 接收并打印消息（可选：保存到文件或 bag）
- 支持过滤特定话题类型或名称

运行示例:
  python3 monitor/all_topics_monitor.py -h
  python3 monitor/all_topics_monitor.py --ros-args -p print_messages:=true -p save_to_file:=false
"""

import sys
import rclpy
from rclpy.node import Node
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from rclpy.qos import qos_profile_sensor_data
import time
from datetime import datetime
from collections import defaultdict
from typing import Dict, Set


class AllTopicsMonitor(Node):
    def __init__(self):
        super().__init__('all_topics_monitor')
        
        # 参数
        self.declare_parameter('print_messages', True)
        self.declare_parameter('save_to_file', False)
        self.declare_parameter('topic_filter', '')  # 逗号分隔的话题名称过滤（空=不过滤）
        self.declare_parameter('type_filter', '')  # 逗号分隔的消息类型过滤（空=不过滤）
        self.declare_parameter('discovery_interval', 2.0)  # 话题发现间隔（秒）
        
        self.print_messages = self.get_parameter('print_messages').get_parameter_value().bool_value
        self.save_to_file = self.get_parameter('save_to_file').get_parameter_value().bool_value
        topic_filter_str = self.get_parameter('topic_filter').get_parameter_value().string_value
        type_filter_str = self.get_parameter('type_filter').get_parameter_value().string_value
        self.discovery_interval = float(self.get_parameter('discovery_interval').get_parameter_value().double_value)
        
        # 解析过滤器
        self.topic_filter_set = set(t.strip() for t in topic_filter_str.split(',') if t.strip()) if topic_filter_str else set()
        self.type_filter_set = set(t.strip() for t in type_filter_str.split(',') if t.strip()) if type_filter_str else set()
        
        # 存储
        self.topic_subscriptions: Dict[str, any] = {}
        self.callback_groups: Dict[str, MutuallyExclusiveCallbackGroup] = {}
        self.message_counts: Dict[str, int] = defaultdict(int)
        self.last_message_time: Dict[str, float] = {}
        
        # 文件保存
        if self.save_to_file:
            import os
            log_dir = os.path.join(os.path.dirname(__file__), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.log_file = os.path.join(log_dir, f'all_topics_log_{timestamp}.txt')
            self.log_file_handle = open(self.log_file, 'w', encoding='utf-8')
            self.get_logger().info(f'日志文件: {self.log_file}')
        else:
            self.log_file_handle = None
        
        # 定时发现新话题
        self.create_timer(self.discovery_interval, self._discover_topics)
        
        # 立即执行一次发现
        self._discover_topics()
        
        self.get_logger().info(
            f'All topics monitor started: print={self.print_messages}, save_file={self.save_to_file}, '
            f'topic_filter={len(self.topic_filter_set)}, type_filter={len(self.type_filter_set)}'
        )
    
    def _should_subscribe(self, topic_name: str, topic_type: str) -> bool:
        """判断是否应该订阅该话题"""
        # 跳过图像话题（不需要接收图像数据）
        if 'sensor_msgs/msg/Image' in topic_type:
            return False
        
        # 话题名称过滤
        if self.topic_filter_set:
            if not any(f in topic_name for f in self.topic_filter_set):
                return False
        
        # 消息类型过滤
        if self.type_filter_set:
            if topic_type not in self.type_filter_set:
                return False
        
        return True
    
    def _discover_topics(self):
        """发现并订阅新话题"""
        try:
            # 获取所有话题和类型
            topic_names_and_types = self.get_topic_names_and_types()
            
            for topic_name, topic_types in topic_names_and_types:
                # 跳过已订阅的话题
                if topic_name in self.topic_subscriptions:
                    continue
                
                # 使用第一个类型（通常只有一个）
                if not topic_types:
                    continue
                topic_type = topic_types[0]
                
                # 过滤检查
                if not self._should_subscribe(topic_name, topic_type):
                    continue
                
                # 尝试订阅
                try:
                    self._subscribe_topic(topic_name, topic_type)
                except Exception as e:
                    self.get_logger().warn(f'订阅话题失败 {topic_name} [{topic_type}]: {e}')
        
        except Exception as e:
            self.get_logger().error(f'发现话题失败: {e}')
    
    def _subscribe_topic(self, topic_name: str, topic_type: str):
        """订阅指定话题"""
        try:
            # 动态导入消息类型
            from rosidl_runtime_py.utilities import get_message
            
            msg_class = get_message(topic_type)
            
            # 创建回调组
            callback_group = MutuallyExclusiveCallbackGroup()
            self.callback_groups[topic_name] = callback_group
            
            # 根据话题类型和名称智能选择 QoS
            # 图像话题：前视用 RELIABLE，左右用 BEST_EFFORT
            if 'sensor_msgs/msg/Image' in topic_type:
                if '/cam_left' in topic_name or '/cam_right' in topic_name:
                    # 左右摄像头：BEST_EFFORT
                    qos_profiles = [
                        QoSProfile(
                            reliability=ReliabilityPolicy.BEST_EFFORT,
                            history=HistoryPolicy.KEEP_LAST,
                            depth=10,
                            durability=DurabilityPolicy.VOLATILE
                        ),
                    ]
                else:
                    # 前视或其他图像：先尝试 RELIABLE，再尝试 BEST_EFFORT
                    qos_profiles = [
                        QoSProfile(
                            reliability=ReliabilityPolicy.RELIABLE,
                            history=HistoryPolicy.KEEP_LAST,
                            depth=10,
                            durability=DurabilityPolicy.VOLATILE
                        ),
                        QoSProfile(
                            reliability=ReliabilityPolicy.BEST_EFFORT,
                            history=HistoryPolicy.KEEP_LAST,
                            depth=10,
                            durability=DurabilityPolicy.VOLATILE
                        ),
                    ]
            else:
                # 其他话题：尝试多种策略
                qos_profiles = [
                    qos_profile_sensor_data,  # 传感器数据常用
                    QoSProfile(
                        reliability=ReliabilityPolicy.RELIABLE,
                        history=HistoryPolicy.KEEP_LAST,
                        depth=10,
                        durability=DurabilityPolicy.VOLATILE
                    ),
                    QoSProfile(
                        reliability=ReliabilityPolicy.BEST_EFFORT,
                        history=HistoryPolicy.KEEP_LAST,
                        depth=10,
                        durability=DurabilityPolicy.VOLATILE
                    ),
                ]
            
            # 尝试订阅（使用第一个成功的 QoS）
            subscription = None
            for qos in qos_profiles:
                try:
                    subscription = self.create_subscription(
                        msg_class,
                        topic_name,
                        lambda msg, tn=topic_name, tt=topic_type: self._message_callback(msg, tn, tt),
                        qos,
                        callback_group=callback_group
                    )
                    break
                except Exception:
                    continue
            
            if subscription is None:
                self.get_logger().warn(f'无法订阅话题 {topic_name} [{topic_type}]（QoS 不兼容）')
                return
            
            self.topic_subscriptions[topic_name] = {
                'subscription': subscription,
                'type': topic_type,
                'qos': qos
            }
            
            self.get_logger().info(f'✓ 订阅话题: {topic_name} [{topic_type}]')
            
        except Exception as e:
            self.get_logger().error(f'订阅话题 {topic_name} 失败: {e}')
    
    def _message_callback(self, msg, topic_name: str, topic_type: str):
        """消息回调函数"""
        self.message_counts[topic_name] += 1
        self.last_message_time[topic_name] = time.time()
        
        # 获取消息时间戳（如果有）
        msg_time_str = ''
        try:
            if hasattr(msg, 'header') and hasattr(msg.header, 'stamp'):
                stamp = msg.header.stamp
                msg_time_ms = stamp.sec * 1000.0 + stamp.nanosec / 1_000_000.0
                msg_time_str = f' stamp={msg_time_ms:.3f}ms'
        except Exception:
            pass
        
        # 打印消息
        if self.print_messages:
            count = self.message_counts[topic_name]
            self.get_logger().info(f'[{topic_name}] 消息 #{count}{msg_time_str} [{topic_type}]')
        
        # 保存到文件
        if self.log_file_handle:
            try:
                wall_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                log_line = f"[{wall_time}] {topic_name} [{topic_type}] count={self.message_counts[topic_name]}{msg_time_str}\n"
                self.log_file_handle.write(log_line)
                self.log_file_handle.flush()
            except Exception as e:
                self.get_logger().error(f'写入日志文件失败: {e}')
    
    def destroy_node(self):
        """清理资源"""
        # 打印统计
        self.get_logger().info('=' * 60)
        self.get_logger().info('统计信息:')
        self.get_logger().info(f'总订阅话题数: {len(self.topic_subscriptions)}')
        for topic_name, count in sorted(self.message_counts.items(), key=lambda x: x[1], reverse=True):
            last_time = self.last_message_time.get(topic_name, 0)
            if last_time > 0:
                elapsed = time.time() - last_time
                self.get_logger().info(f'  {topic_name}: {count} 条消息 (最后接收: {elapsed:.1f}秒前)')
            else:
                self.get_logger().info(f'  {topic_name}: {count} 条消息')
        self.get_logger().info('=' * 60)
        
        # 关闭文件
        if self.log_file_handle:
            try:
                self.log_file_handle.close()
                self.get_logger().info(f'日志文件已保存: {self.log_file}')
            except Exception:
                pass
        
        super().destroy_node()


def main(args=None):
    def print_usage():
        print(
            """
用法:
  python3 monitor/all_topics_monitor.py [-h]
  python3 monitor/all_topics_monitor.py --ros-args \
    -p print_messages:=true -p save_to_file:=false \
    -p topic_filter:=/camera,/sensor -p type_filter:=sensor_msgs/msg/Image

参数说明(ROS 参数):
  print_messages    : 是否打印消息到终端, 默认 true
  save_to_file     : 是否保存到文件, 默认 false
  topic_filter     : 话题名称过滤(逗号分隔, 空=不过滤), 默认 ''
  type_filter      : 消息类型过滤(逗号分隔, 空=不过滤), 默认 ''
  discovery_interval: 话题发现间隔(秒), 默认 2.0

说明:
  - 自动发现并订阅所有 ROS2 话题
  - 支持按话题名称或消息类型过滤
  - 自动尝试多种 QoS 策略以兼容不同话题
""".strip()
        )
    
    if args is None:
        args = sys.argv
    if any(a in ("-h", "--help") for a in args[1:]):
        print_usage()
        return
    
    rclpy.init(args=args)
    
    node = AllTopicsMonitor()
    
    # 使用多线程执行器，支持大量订阅
    from rclpy.executors import MultiThreadedExecutor
    executor = MultiThreadedExecutor(num_threads=8)
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

