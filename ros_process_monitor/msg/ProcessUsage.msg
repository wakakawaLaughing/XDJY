# Single process (by name) usage metrics, aggregated across all PIDs with the same name
std_msgs/Header header
string name
float32 cpu_percent          # 0.0 - 100.0 per logical CPU scaled by psutil, aggregated
float32 mem_percent          # percent of system memory used by this process group
uint64 rss_bytes             # resident set size (bytes)
uint64 vms_bytes             # virtual memory size (bytes)

