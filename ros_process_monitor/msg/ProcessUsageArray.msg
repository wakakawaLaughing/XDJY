# Aggregated usage metrics for a set of process names
std_msgs/Header header
float32 total_cpu_percent    # sum of cpu_percent across tracked names
float32 total_mem_percent    # sum of mem_percent across tracked names
ros_process_monitor/ProcessUsage[] processes

