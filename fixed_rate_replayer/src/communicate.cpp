#include "fixed_rate_replayer/communicate.hpp"

#include <rclcpp/serialized_message.hpp>
#include <rclcpp/generic_publisher.hpp>

#include <condition_variable>
#include <deque>
#include <mutex>
#include <thread>

#include <zmq.h>

namespace fixed_rate_replayer {

class CommunicateRos final : public Communicate {
public:
  explicit CommunicateRos(const rclcpp::Logger & logger) : logger_(logger) {}

  void Initialize(rclcpp::Node * node,
                  const std::unordered_map<std::string, std::string> & topic_to_type) override {
    node_ = node;
    topic_to_type_ = topic_to_type;
  }

  void Publish(const std::string & topic,
               const std::shared_ptr<std::vector<uint8_t>> & payload) override {
    if (!node_) {
      return;
    }
    auto pub = GetOrCreatePublisher(topic);
    if (!pub) {
      return;
    }
    rclcpp::SerializedMessage smsg(payload->size());
    std::memcpy(smsg.get_rcl_serialized_message().buffer, payload->data(), payload->size());
    pub->publish(smsg);
  }
private:
  std::shared_ptr<rclcpp::GenericPublisher> GetOrCreatePublisher(const std::string & topic) {
    auto it = pubs_.find(topic);
    if (it != pubs_.end()) {
      return it->second;
    }
    auto it_type = topic_to_type_.find(topic);
    if (it_type == topic_to_type_.end()) {
      RCLCPP_WARN(logger_, "No type for topic %s; skip creating publisher", topic.c_str());
      return nullptr;
    }
    auto qos = rclcpp::QoS(rclcpp::KeepLast(10));
    auto pub = node_->create_generic_publisher(topic, it_type->second, qos);
    pubs_[topic] = pub;
    return pub;
  }

  rclcpp::Logger logger_;
  rclcpp::Node * node_{nullptr};
  std::unordered_map<std::string, std::string> topic_to_type_;
  std::unordered_map<std::string, std::shared_ptr<rclcpp::GenericPublisher>> pubs_;
};

class CommunicateZmq final : public Communicate {
public:
  CommunicateZmq(const std::string & address, const rclcpp::Logger & logger)
  : logger_(logger), address_(address) {
    sender_thread_ = std::thread([this]() { this->SenderLoop(); });
  }
  ~CommunicateZmq() override {
    {
      std::lock_guard<std::mutex> lk(mutex_);
      stop_ = true;
    }
    cv_.notify_all();
    if (sender_thread_.joinable()) {
      sender_thread_.join();
    }
  }

  void Publish(const std::string & topic,
               const std::shared_ptr<std::vector<uint8_t>> & payload) override {
    std::lock_guard<std::mutex> lk(mutex_);
    queue_.emplace_back(Item{topic, payload});
    cv_.notify_one();
  }
  void Initialize(rclcpp::Node * /*node*/,
                  const std::unordered_map<std::string, std::string> & /*topic_to_type*/) override {}

private:
  struct Item { std::string topic; std::shared_ptr<std::vector<uint8_t>> payload; };
  void SenderLoop() {
    void* ctx = zmq_ctx_new();
    void* sock = zmq_socket(ctx, ZMQ_PUB);
    if (zmq_bind(sock, address_.c_str()) != 0) {
      RCLCPP_FATAL(logger_, "ZMQ bind failed: %s", zmq_strerror(zmq_errno()));
    } else {
      RCLCPP_INFO(logger_, "ZMQ publisher bound at %s", address_.c_str());
    }
    while (true) {
      Item item;
      {
        std::unique_lock<std::mutex> lk(mutex_);
        cv_.wait(lk, [&]{ return stop_ || !queue_.empty(); });
        if (stop_ && queue_.empty()) {
          break;
        }
        item = std::move(queue_.front());
        queue_.pop_front();
      }
      zmq_msg_t topic_msg;
      zmq_msg_init_size(&topic_msg, item.topic.size());
      std::memcpy(zmq_msg_data(&topic_msg), item.topic.data(), item.topic.size());
      zmq_msg_send(&topic_msg, sock, ZMQ_SNDMORE);
      zmq_msg_close(&topic_msg);
      zmq_msg_t data_msg;
      zmq_msg_init_size(&data_msg, item.payload->size());
      std::memcpy(zmq_msg_data(&data_msg), item.payload->data(), item.payload->size());
      zmq_msg_send(&data_msg, sock, 0);
      zmq_msg_close(&data_msg);
    }
    zmq_close(sock);
    zmq_ctx_term(ctx);
  }

  rclcpp::Logger logger_;
  std::string address_;
  std::deque<Item> queue_;
  std::mutex mutex_;
  std::condition_variable cv_;
  std::thread sender_thread_;
  bool stop_{false};
};

std::shared_ptr<Communicate> CreateCommunicator(const std::string & transport,
                                                const std::string & zmq_address,
                                                const rclcpp::Logger & logger) {
  if (transport == std::string("zmq")) {
    return std::make_shared<CommunicateZmq>(zmq_address, logger);
  }
  return std::make_shared<CommunicateRos>(logger);
}

} // namespace fixed_rate_replayer


