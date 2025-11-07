cmake_minimum_required(VERSION 3.8)
project(fixed_rate_replayer)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rosbag2_cpp REQUIRED)
find_package(rosbag2_storage REQUIRED)
find_package(rcutils REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(ament_index_cpp REQUIRED)

include_directories(
  include
)

add_executable(fixed_rate_replayer_node
  src/main.cpp
  src/config.cpp
  src/communicate.cpp
  src/replay.cpp
)
ament_target_dependencies(fixed_rate_replayer_node rclcpp rosbag2_cpp rosbag2_storage rcutils nlohmann_json)
ament_target_dependencies(fixed_rate_replayer_node ament_index_cpp)
target_link_libraries(fixed_rate_replayer_node zmq)

add_executable(zmq_dump test/zmq_dump.cpp)
target_link_libraries(zmq_dump zmq)
install(TARGETS zmq_dump DESTINATION lib/${PROJECT_NAME})
target_compile_definitions(fixed_rate_replayer_node PRIVATE
  _DEFAULT_SOURCE
)

target_compile_options(fixed_rate_replayer_node PRIVATE -Wall -Wextra -Wpedantic)

install(TARGETS fixed_rate_replayer_node
  DESTINATION lib/${PROJECT_NAME})

install(DIRECTORY include/
  DESTINATION include/
)

install(DIRECTORY config/
  DESTINATION share/${PROJECT_NAME}/config
)

ament_package()

