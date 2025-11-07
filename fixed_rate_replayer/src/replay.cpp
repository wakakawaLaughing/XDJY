#include "fixed_rate_replayer/replay.hpp"

#include <rclcpp/serialized_message.hpp>

#include <rosbag2_cpp/reader.hpp>
#include <rosbag2_cpp/storage_options.hpp>

#include <cstring>
#include <sstream>

namespace fixed_rate_replayer {

FixedRateReplayer::FixedRateReplayer(const AppConfig & cfg)
: Node("fixed_rate_replayer"), config_(cfg) {
  // create communicator first
  communicator_ = CreateCommunicator(config_.transport, config_.zmq_address, this->get_logger());
  InitializePublishersAndQueues();
  StartThreads();
}

FixedRateReplayer::~FixedRateReplayer() {
  Shutdown();
}

void FixedRateReplayer::InitializePublishersAndQueues() {
  rosbag2_cpp::Reader probe_reader;
  rosbag2_cpp::StorageOptions storage_options; 
  storage_options.uri = config_.bag_path;
  storage_options.storage_id = "sqlite3";
  try {
    probe_reader.open(storage_options);
  } catch (const std::exception & e) {
    RCLCPP_FATAL(get_logger(), "Failed to open bag: %s", e.what());
    throw;
  }
  for (const auto & desc : probe_reader.get_all_topics_and_types()) {
    topic_to_type_[desc.name] = desc.type;
  }
  probe_reader.close();

  bool has_explicit = !config_.topics.empty();
  if (!has_explicit) {
    for (const auto & kv : topic_to_type_) {
      TopicConfig tcfg{config_.default_hz};
      config_.topics.emplace(kv.first, tcfg);
    }
  }

  for (const auto& kv : config_.topics) {
    const std::string& topic = kv.first;
    const double hz = kv.second.hz > 0.0 ? kv.second.hz : config_.default_hz;
    auto it_type = topic_to_type_.find(topic);
    if (it_type == topic_to_type_.end()) {
      RCLCPP_WARN(get_logger(), "Configured topic '%s' not found in bag; skipping", topic.c_str());
      continue;
    }
    auto runtime = std::make_shared<TopicRuntime>();
    runtime->hz = hz;
    topics_[topic] = runtime;
    RCLCPP_INFO(get_logger(), "Prepared topic: %s [%s] at %.3f Hz", topic.c_str(), it_type->second.c_str(), hz);
  }
  communicator_->Initialize(this, topic_to_type_);
}

void FixedRateReplayer::StartThreads() {
  producer_thread_ = std::thread([this]() { ProducerLoop(); });
  for (auto & kv : topics_) {
    auto & topic = kv.first;
    auto & rt = kv.second;
    rt->consumer_running = true;
    rt->consumer_thread = std::thread([this, topic, rt]() { ConsumerLoop(topic, rt); });
  }
  // communicator owns any transport-specific threads
}

void FixedRateReplayer::Shutdown() {
  stop_.store(true);
  for (auto & kv : topics_) {
    kv.second->cv.notify_all();
  }
  if (producer_thread_.joinable()) producer_thread_.join();
  for (auto & kv : topics_) {
    if (kv.second->consumer_thread.joinable()) kv.second->consumer_thread.join();
  }
  communicator_.reset();
}

void FixedRateReplayer::ProducerLoop() {
  do {
    try {
      rosbag2_cpp::Reader reader;
      rosbag2_cpp::StorageOptions storage_options;
      storage_options.uri = config_.bag_path;
      storage_options.storage_id = "sqlite3";
      reader.open(storage_options);

      while (!stop_.load() && reader.has_next()) {
        auto bag_msg = reader.read_next();
        const std::string & topic = bag_msg->topic_name;
        auto it = topics_.find(topic);
        if (it == topics_.end()) {
          continue;
        }
        auto & rt = it->second;

        auto payload = std::make_shared<std::vector<uint8_t>>();
        payload->resize(bag_msg->serialized_data->buffer_length);
        std::memcpy(payload->data(), bag_msg->serialized_data->buffer, bag_msg->serialized_data->buffer_length);

        {
          std::unique_lock<std::mutex> lk(rt->mutex);
          rt->cv.wait(lk, [&]() {
            return stop_.load() || rt->queue.size() < config_.max_queue_per_topic;
          });
          if (stop_.load()) break;
          rt->queue.push_back(OutMessage{payload});
        }
        rt->cv.notify_one();
      }

      reader.close();
    } catch (const std::exception & e) {
      RCLCPP_ERROR(get_logger(), "Producer exception: %s", e.what());
      break;
    }

    producer_finished_.store(true);
    for (auto & kv : topics_) {
      kv.second->cv.notify_all();
    }
    if (stop_.load() || !config_.loop) {
      break;
    }
    producer_finished_.store(false);
  } while (config_.loop && !stop_.load());
}

void FixedRateReplayer::ConsumerLoop(const std::string & topic, const std::shared_ptr<TopicRuntime> & rt) {
  const double hz = rt->hz;
  rclcpp::WallRate rate(hz > 0.0 ? hz : 1.0);
  while (rclcpp::ok() && !stop_.load()) {
    std::shared_ptr<std::vector<uint8_t>> payload;
    {
      std::unique_lock<std::mutex> lk(rt->mutex);
      if (rt->queue.empty()) {
        if (producer_finished_.load() && !config_.loop) {
          break;
        }
      } else {
        payload = rt->queue.front().data;
        rt->queue.pop_front();
        rt->cv.notify_one();
      }
    }

    if (payload) {
      // Keep message concise; rely on RCUTILS_CONSOLE_OUTPUT_FORMAT for timestamp/thread/file
      RCLCPP_INFO(this->get_logger(), "publish topic=%s", topic.c_str());
      communicator_->Publish(topic, payload);
    }

    rate.sleep();
  }
}

} // namespace fixed_rate_replayer


