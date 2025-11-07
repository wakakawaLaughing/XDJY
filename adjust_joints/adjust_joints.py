#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import threading
import time
import os
import json

from xbot_common_interfaces.msg import HybridJointCommand
from sensor_msgs.msg import JointState

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
import sys


class JointAdjuster(Node):
    """自动调整关节到配置文件中的目标位置"""

    def __init__(self):
        super().__init__('joint_adjuster')
        self._state_lock = threading.Lock()
        self.joint_states = None
        self.subscription = self.create_subscription(
            JointState,
            'joint_states',
            self.joint_states_cb,
            10)

        # Declare parameters (with defaults) and get their values
        self.declare_parameters(
            namespace='',
            parameters=[
                ('joint_names', []),
                ('duration', 5.0),
                ('kp', [100.0]),
                ('kd', [0.0])
            ]
        )
        self.declare_parameter('controller_topic_name', '/wr1_controller/commands')
        # 配置路径参数，默认使用脚本同目录下的 config.json
        default_config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        self.declare_parameter('config_path', default_config_path)
        
        self.joint_names = self.get_parameter('joint_names').value
        # 若 joint_names 未提供，则从配置文件自动推断
        if not self.joint_names:
            cfg_try = self._read_config()
            if isinstance(cfg_try, dict) and cfg_try:
                self.joint_names = list(cfg_try.keys())
        self.duration = float(self.get_parameter('duration').value)
        self.kp = self.get_parameter('kp').value
        self.kd = self.get_parameter('kd').value
        self.controller_topic_name = self.get_parameter('controller_topic_name').value
        self.hybrid_cmd_pub_ = self.create_publisher(HybridJointCommand, f'{self.controller_topic_name}', 1)
        self.current_positions = {}
        # 初始化为 0，然后用配置文件中的值覆盖
        self.target_positions = {name: 0.0 for name in self.joint_names}

        # 读取配置文件，覆盖目标位置（仅覆盖配置中出现的关节）
        self.load_target_positions_from_config()

    def _read_config(self):
        config_path = self.get_parameter('config_path').value
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception:
            return None
        
        # 标记（不使用线程/定时器自动触发）
        self.moving = False
        self.movement_thread = None
        self.get_logger().info('节点已启动，等待主程序触发移动...')

    def load_target_positions_from_config(self):
        config_path = self.get_parameter('config_path').value
        try:
            with open(config_path, 'r') as f:
                cfg = json.load(f)
            if not isinstance(cfg, dict):
                raise ValueError('config.json 必须是 {joint_name: position} 的字典')
            applied = {}
            for name, pos in cfg.items():
                if name in self.target_positions:
                    try:
                        self.target_positions[name] = float(pos)
                        applied[name] = self.target_positions[name]
                    except Exception:
                        self.get_logger().warn(f'配置中关节 {name} 的值无法转换为 float: {pos}')
            if applied:
                self.get_logger().info(f'已从配置文件加载目标位置: {applied}')
            else:
                self.get_logger().warn('配置文件未匹配到任何已声明的关节名，目标保持为 0.0')
        except FileNotFoundError:
            self.get_logger().warn(f'未找到配置文件: {config_path}，将使用默认目标 0.0')
        except Exception as e:
            self.get_logger().warn(f'读取配置文件失败: {e}，将使用默认目标 0.0')

    def joint_states_cb(self, msg):
        with self._state_lock:
            self.joint_states = msg
        # 仅保存当前位置，不在回调中触发运动

    def destroy(self):
        self.moving = False
        super().destroy_node()

    def set_joint_positions(self, positions):
        # 设置关节位置的函数
        self.current_positions = positions
        cmd = HybridJointCommand()
        cmd.header.stamp = self.get_clock().now().to_msg()
        cmd.joint_name = self.joint_names
        for i in range(len(self.joint_names)):
            cmd.position.append(positions[self.joint_names[i]])
        cmd.velocity = [0.0] * len(self.joint_names)
        cmd.feedforward = [0.0] * len(self.joint_names)
        cmd.kp = self.kp
        cmd.kd = self.kd
        self.hybrid_cmd_pub_.publish(cmd)
        
        #self.get_logger().info(f'Setting joint positions: {positions}')

    def get_joint_positions(self):
        with self._state_lock:
            if self.joint_states is None:
                return dict(self.current_positions)
            name_to_pos = dict(zip(self.joint_states.name, self.joint_states.position))
        # 只提取关心的关节，并更新缓存
        snapshot = {}
        for name in self.joint_names:
            if name in name_to_pos:
                self.current_positions[name] = float(name_to_pos[name])
                snapshot[name] = float(name_to_pos[name])
            elif name in self.current_positions:
                snapshot[name] = float(self.current_positions[name])
        return snapshot

    def linear_interpolation(self, start_pos, end_pos, start_time, end_time, current_time):
        # 线性插值计算
        if current_time >= end_time:
            return end_pos
        elif current_time <= start_time:
            return start_pos
        else:
            return start_pos + (end_pos - start_pos) * (current_time - start_time) / (end_time - start_time)

    def move_to_target(self):
        """同步执行：将关节移动到目标位置。调用前应确保 joint_states 已就绪。"""
        self.moving = True
        # 等到所有目标关节在 joint_states 中出现
        start_time_wait = time.time()
        while True:
            with self._state_lock:
                ready = (
                    self.joint_states is not None and
                    all(name in (self.joint_states.name if self.joint_states else []) for name in self.joint_names)
                )
            if ready:
                break
            if time.time() - start_time_wait > 5.0:
                self.get_logger().warn('等待 joint_states 包含所有目标关节超时，使用已有值/0.0 作为起点')
                break
            rclpy.spin_once(self, timeout_sec=0.1)

        start_positions = self.get_joint_positions()
        # 确保起点对每个关节都有值
        for name in self.joint_names:
            if name not in start_positions:
                start_positions[name] = float(self.current_positions.get(name, 0.0))
        end_positions = self.target_positions.copy()
        
        self.get_logger().info(f'开始移动到目标位置: {end_positions}')
        self.get_logger().info(f'起始位置: {start_positions}')
        
        start_time = time.time()
        end_time = start_time + self.duration
        
        while time.time() < end_time and self.moving:
            current_time = time.time()
            new_positions = {}
            for joint in self.joint_names:
                new_positions[joint] = self.linear_interpolation(
                    start_positions[joint], 
                    end_positions[joint], 
                    start_time, 
                    end_time, 
                    current_time
                )
            self.set_joint_positions(new_positions)
            time.sleep(0.01)
        
        if self.moving:
            # 最终确保关节到达目标位置
            self.set_joint_positions(end_positions)
            self.get_logger().info('已到达目标位置')
        else:
            self.get_logger().info('移动被中断')


def main(args=None):
    rclpy.init(args=args)

    node = JointAdjuster()

    try:
        # 先轮询直到 joint_states 就绪
        node.get_logger().info('等待 joint_states 就绪后开始移动...')
        while node.joint_states is None:
            rclpy.spin_once(node, timeout_sec=0.1)
        # 再执行一次性移动到目标
        node.move_to_target()
    except KeyboardInterrupt:
        pass
    except ExternalShutdownException:
        sys.exit(1)
    finally:
        node.destroy()
        if rclpy.ok():
            rclpy.shutdown()
    


if __name__ == '__main__':
    main()

