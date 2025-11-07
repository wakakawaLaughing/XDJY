#include <rclcpp/rclcpp.hpp>

#include "fixed_rate_replayer/config.hpp"
#include "fixed_rate_replayer/replay.hpp"

#include <ament_index_cpp/get_package_share_directory.hpp>
#include <filesystem>
#include <cstdlib>

using fixed_rate_replayer::AppConfig;
using fixed_rate_replayer::FixedRateReplayer;
using fixed_rate_replayer::LoadConfig;

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  std::string config_path;
  for (int i = 1; i < argc; ++i) {
    std::string arg(argv[i]);
    if (arg == "--config" && i + 1 < argc) {
      config_path = argv[++i];
    }
  }
  auto bootstrap = rclcpp::Node("fixed_rate_replayer_bootstrap");

  std::optional<AppConfig> cfg_opt;
  if (!config_path.empty()) {
    cfg_opt = LoadConfig(config_path, bootstrap.get_logger());
    if (!cfg_opt) {
      RCLCPP_WARN(bootstrap.get_logger(), "Failed to load provided config. Will try defaults.");
    }
  }

  if (!cfg_opt) {
    // Try package default config
    try {
      auto share = ament_index_cpp::get_package_share_directory("fixed_rate_replayer");
      std::string default_cfg = share + std::string("/config/config.json");
      if (std::filesystem::exists(default_cfg)) {
        cfg_opt = LoadConfig(default_cfg, bootstrap.get_logger());
      }
    } catch (const std::exception & ) {
      // ignore, fallback below
    }
  }

  if (!cfg_opt) {
    // Built-in defaults
    AppConfig cfg;
    const char* env_bag = std::getenv("BAG_PATH");
    cfg.bag_path = env_bag ? std::string(env_bag) : std::string(".");
    cfg.default_hz = 50.0;
    cfg.loop = false;
    cfg.max_queue_per_topic = 2000;
    // topics empty → all topics at default_hz
    RCLCPP_WARN(bootstrap.get_logger(), "Using built-in defaults: bag_path='%s', hz=%.1f, loop=%s",
      cfg.bag_path.c_str(), cfg.default_hz, cfg.loop ? "true" : "false");
    cfg_opt = cfg;
  }

  auto node = std::make_shared<FixedRateReplayer>(*cfg_opt);
  rclcpp::executors::SingleThreadedExecutor exec;
  exec.add_node(node);
  exec.spin();
  rclcpp::shutdown();
  return 0;
}


