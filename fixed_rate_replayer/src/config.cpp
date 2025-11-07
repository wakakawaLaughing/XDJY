#include "fixed_rate_replayer/config.hpp"

#include <nlohmann/json.hpp>
#include <rclcpp/rclcpp.hpp>

#include <fstream>

namespace fixed_rate_replayer {

using json = nlohmann::json;

std::optional<AppConfig> LoadConfig(const std::string & path, const rclcpp::Logger & logger) {
  std::ifstream ifs(path);
  if (!ifs.is_open()) {
    RCLCPP_ERROR(logger, "Failed to open config file: %s", path.c_str());
    return std::nullopt;
  }
  json j;
  try {
    ifs >> j;
  } catch (const std::exception & e) {
    RCLCPP_ERROR(logger, "Failed to parse JSON: %s", e.what());
    return std::nullopt;
  }
  AppConfig cfg;
  if (j.contains("bag_path")) cfg.bag_path = j.at("bag_path").get<std::string>();
  if (cfg.bag_path.empty()) {
    RCLCPP_ERROR(logger, "config.json missing 'bag_path'");
    return std::nullopt;
  }
  if (j.contains("hz")) cfg.default_hz = j.at("hz").get<double>();
  if (j.contains("loop")) cfg.loop = j.at("loop").get<bool>();
  if (j.contains("max_queue_per_topic")) cfg.max_queue_per_topic = j.at("max_queue_per_topic").get<std::size_t>();
  if (j.contains("transport")) cfg.transport = j.at("transport").get<std::string>();
  if (j.contains("zmq_address")) cfg.zmq_address = j.at("zmq_address").get<std::string>();
  if (j.contains("topics")) {
    for (auto it = j.at("topics").begin(); it != j.at("topics").end(); ++it) {
      TopicConfig t;
      if (it.value().contains("hz")) t.hz = it.value().at("hz").get<double>();
      cfg.topics.emplace(it.key(), t);
    }
  }
  if (cfg.default_hz <= 0.0) {
    RCLCPP_ERROR(logger, "config.json: 'hz' must be > 0");
    return std::nullopt;
  }
  return cfg;
}

} // namespace fixed_rate_replayer


