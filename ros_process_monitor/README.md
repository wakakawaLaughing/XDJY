## ros_process_monitor

Publish CPU and memory usage for specified processes as ROS 2 messages every 2 seconds.

### Messages
- `ros_process_monitor/ProcessUsage`
  - `string name`
  - `float32 cpu_percent`
  - `float32 mem_percent`
  - `uint64 rss_bytes`
  - `uint64 vms_bytes`
  - `builtin_interfaces/Time stamp`

- `ros_process_monitor/ProcessUsageArray`
  - `builtin_interfaces/Time stamp`
  - `float32 total_cpu_percent`
  - `float32 total_mem_percent`
  - `ProcessUsage[] processes`

### Build
```bash
# 在工程目录内本地构建（无需拷贝/软链接）
cd /root/code/tmp/ros_process_monitor
source /opt/ros/humble/setup.bash

# 构建
colcon build --base-paths . --packages-select ros_process_monitor

# 加载环境
source install/setup.bash
```

### Run (no parameters required)
The node auto-loads config from package share:
`$(ros2 pkg prefix ros_process_monitor)/share/ros_process_monitor/config/process_config.json`

```bash
ros2 run ros_process_monitor process_monitor_node
```

Optional override a different config path:
```bash
ros2 run ros_process_monitor process_monitor_node \
  --ros-args -p config_file:=/path/to/your_config.json
```

### Notes
- CPU percentages are aggregated across all PIDs that share the same process name.
- First sample is primed to avoid initial 0.0 CPU%.
- Requires `psutil` (installed via `rosdep` or Python package manager).
- Config JSON is hot-reloaded on change; topic/interval updates take effect immediately.

### Config format
`process_config.json` example:
```json
{
  "process_names": ["python3", "ros2", "rviz2"],
  "publish_topic": "/process_usage",
  "publish_interval_sec": 2.0
}
```


