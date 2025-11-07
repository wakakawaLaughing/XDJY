#pragma once

#include <map>
#include <optional>
#include <string>
#include <rclcpp/rclcpp.hpp>

namespace fixed_rate_replayer {

struct TopicConfig {
  double hz{0.0};
};

struct AppConfig {
  std::string bag_path;
  double default_hz{0.0};
  bool loop{false};
  std::size_t max_queue_per_topic{1000};
  std::string transport{"ros"}; // ros | zmq
  std::string zmq_address{"tcp://*:5555"};
  std::map<std::string, TopicConfig> topics; // name -> config
};

std::optional<AppConfig> LoadConfig(const std::string & path, const rclcpp::Logger & logger);

} // namespace fixed_rate_replayer


