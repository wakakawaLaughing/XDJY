cmake_minimum_required(VERSION 3.8)
project(ros_process_monitor)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)

set(MSG_FILES
  "msg/ProcessUsage.msg"
  "msg/ProcessUsageArray.msg"
)

rosidl_generate_interfaces(${PROJECT_NAME}
  ${MSG_FILES}
  DEPENDENCIES std_msgs
)

# Install the Python runtime package. Use a distinct name to avoid clashing
# with the auto-generated Python package for interfaces (rosidl_generator_py).
ament_python_install_package(ros_process_monitor_py)

# Explicitly install a launcher script into lib/${PROJECT_NAME} so `ros2 run` can find it
install(PROGRAMS
  scripts/process_monitor_node
  DESTINATION lib/${PROJECT_NAME}
)

# Install configuration files to package share
install(DIRECTORY
  config/
  DESTINATION share/${PROJECT_NAME}/config
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()

