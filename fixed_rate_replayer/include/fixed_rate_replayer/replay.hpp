#pragma once

#include <rclcpp/rclcpp.hpp>

#include <condition_variable>
#include <deque>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include "fixed_rate_replayer/config.hpp"
#include "fixed_rate_replayer/communicate.hpp"

namespace fixed_rate_replayer {

struct OutMessage {
  std::shared_ptr<std::vector<uint8_t>> data;
};

class FixedRateReplayer : public rclcpp::Node {
public:
  explicit FixedRateReplayer(const AppConfig & cfg);
  ~FixedRateReplayer() override;

private:
  struct TopicRuntime {
    std::deque<OutMessage> queue;
    std::mutex mutex;
    std::condition_variable cv;
    double hz{0.0};
    bool consumer_running{false};
    std::thread consumer_thread;
  };

  void InitializePublishersAndQueues();
  void StartThreads();
  void Shutdown();
  void ProducerLoop();
  void ConsumerLoop(const std::string & topic, const std::shared_ptr<TopicRuntime> & rt);

  AppConfig config_;
  std::unordered_map<std::string, std::string> topic_to_type_;
  std::unordered_map<std::string, std::shared_ptr<TopicRuntime>> topics_;

  std::thread producer_thread_;
  std::atomic<bool> stop_{false};
  std::atomic<bool> producer_finished_{false};

  std::shared_ptr<Communicate> communicator_;
};

} // namespace fixed_rate_replayer


