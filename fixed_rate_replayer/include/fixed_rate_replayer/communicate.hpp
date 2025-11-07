#pragma once

#include <memory>
#include <string>
#include <vector>

#include <rclcpp/rclcpp.hpp>
#include <unordered_map>

namespace fixed_rate_replayer {

class Communicate {
public:
  virtual ~Communicate() = default;
  virtual void Initialize(rclcpp::Node * node,
                          const std::unordered_map<std::string, std::string> & topic_to_type) = 0;
  virtual void Publish(const std::string & topic,
                       const std::shared_ptr<std::vector<uint8_t>> & payload) = 0;
};

std::shared_ptr<Communicate> CreateCommunicator(const std::string & transport,
                                                const std::string & zmq_address,
                                                const rclcpp::Logger & logger);

} // namespace fixed_rate_replayer


