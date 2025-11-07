#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from sensor_msgs.msg import JointState
from xbot_common_interfaces.srv import SetJointFloat32Param
import time
import sys
import threading


class AdjustWaistOffset(Node):
    """通过线性插值多次调用服务，平滑设置 `waist_yaw_joint` 的 offset 到 target。"""

    def __init__(self, target: float):
        super().__init__('adjust_waist_offset')
        self.target = float(target)
        self.joint_name = 'waist_yaw_joint'

        # 订阅关节状态
        self._state_lock = threading.Lock()
        self.joint_states = None
        self.subscription = self.create_subscription(
            JointState,
            'joint_offsets',
            self._joint_states_cb,
            10,
        )

        # 服务客户端
        self.client = self.create_client(SetJointFloat32Param, '/set_joint_offset')
        if not self.client.wait_for_service(timeout_sec=5.0):
            self.get_logger().warn('等待 /set_joint_offset 服务超时，将继续重试...')

        # 固定插值时长与频率（仅一个参数 target，保持简单）
        self.duration = 3.0    # 秒
        self.rate_hz = 100.0   # 调用频率

        # 开始执行
        self.timer = self.create_timer(0.1, self._kickoff_once)
        self._started = False

    def _joint_states_cb(self, msg: JointState) -> None:
        with self._state_lock:
            self.joint_states = msg

    def _kickoff_once(self) -> None:
        if self._started:
            return
        # 需要关节状态准备好
        with self._state_lock:
            # joint_offsets 可能为空或不包含目标关节名；此时按 0 作为当前值，也允许继续
            ready = self.joint_states is not None
        if not ready:
            self.get_logger().debug('等待关节状态初始化...')
            return

        self._started = True
        self.timer.cancel()
        self.get_logger().info(f'准备将 {self.joint_name} 的 offset 调整到 {self.target:.3f}')
        self._run_interpolation()

    def _get_current_value(self) -> float:
        with self._state_lock:
            name_to_pos = dict(zip(self.joint_states.name, self.joint_states.position))
            return float(name_to_pos.get(self.joint_name, 0.0))

    def _interp(self, start_v: float, end_v: float, t0: float, t1: float, t: float) -> float:
        if t >= t1:
            return end_v
        if t <= t0:
            return start_v
        ratio = (t - t0) / max(1e-6, (t1 - t0))
        return start_v + (end_v - start_v) * ratio

    def _call_service(self, value: float) -> None:
        if not self.client.service_is_ready():
            if not self.client.wait_for_service(timeout_sec=1.0):
                self.get_logger().warn('服务不可用，跳过本次设置'); return
        req = SetJointFloat32Param.Request()
        req.joint_name = [self.joint_name]
        req.param_value = [float(value)]
        future = self.client.call_async(req)
        print(value)
        # 非阻塞返回；这里不需要等待结果，但可选择等待一小会观察失败
        # rclpy.spin_until_future_complete(self, future, timeout_sec=0.1)

    def _run_interpolation(self) -> None:
        start_val = self._get_current_value()
        end_val = self.target
        t0 = time.time()
        t1 = t0 + self.duration
        self.get_logger().info(f'起点={start_val:.3f}, 终点={end_val:.3f}, 用时={self.duration:.2f}s')

        period = 1.0 / self.rate_hz
        while True:
            now = time.time()
            if now >= t1:
                break
            v = self._interp(start_val, end_val, t0, t1, now)
            self._call_service(v)
            time.sleep(period)

        # 最后一跳确保到达目标
        self._call_service(end_val)
        self.get_logger().info('offset 调整完成')


def main():
    rclpy.init()

    if len(sys.argv) < 2:
        print('用法: adjust_waist.py <target>')
        sys.exit(2)
    try:
        target = float(sys.argv[1])
    except Exception:
        print('target 参数需要是浮点数，例如: 1.57')
        sys.exit(2)

    node = AdjustWaistOffset(target)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except ExternalShutdownException:
        sys.exit(1)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()


