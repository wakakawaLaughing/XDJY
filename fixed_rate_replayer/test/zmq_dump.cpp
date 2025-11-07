#include <zmq.h>

#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

static volatile bool g_stop = false;

static void handle_sigint(int) {
  g_stop = true;
}

static std::string hex_preview(const uint8_t* data, size_t len, size_t max_bytes = 32) {
  static const char* hex = "0123456789ABCDEF";
  size_t n = len < max_bytes ? len : max_bytes;
  std::string out;
  out.reserve(n * 3);
  for (size_t i = 0; i < n; ++i) {
    uint8_t b = data[i];
    out.push_back(hex[(b >> 4) & 0xF]);
    out.push_back(hex[b & 0xF]);
    if (i + 1 < n) out.push_back(' ');
  }
  if (len > n) out += " ...";
  return out;
}

int main(int argc, char** argv) {
  const char* address = "tcp://127.0.0.1:5555";
  if (argc >= 3 && std::string(argv[1]) == "--address") {
    address = argv[2];
  }

  std::signal(SIGINT, handle_sigint);

  void* ctx = zmq_ctx_new();
  void* sock = zmq_socket(ctx, ZMQ_SUB);
  int rc = zmq_connect(sock, address);
  if (rc != 0) {
    std::cerr << "ZMQ connect failed: " << zmq_strerror(zmq_errno()) << std::endl;
    return 1;
  }
  // subscribe to all topics
  zmq_setsockopt(sock, ZMQ_SUBSCRIBE, "", 0);

  std::cout << "ZMQ dump subscribing at " << address << std::endl;

  while (!g_stop) {
    zmq_msg_t topic_msg;
    zmq_msg_init(&topic_msg);
    int more = 0;
    size_t more_size = sizeof(more);

    int r = zmq_msg_recv(&topic_msg, sock, 0);
    if (r == -1) {
      if (zmq_errno() == ETERM || zmq_errno() == EINTR) {
        zmq_msg_close(&topic_msg);
        break;
      }
      continue;
    }
    zmq_getsockopt(sock, ZMQ_RCVMORE, &more, &more_size);
    std::string topic;
    topic.assign(static_cast<const char*>(zmq_msg_data(&topic_msg)), zmq_msg_size(&topic_msg));
    zmq_msg_close(&topic_msg);

    if (!more) {
      std::cout << "[WARN] received single-part message, topic='" << topic << "'" << std::endl;
      continue;
    }

    zmq_msg_t data_msg;
    zmq_msg_init(&data_msg);
    r = zmq_msg_recv(&data_msg, sock, 0);
    if (r == -1) {
      zmq_msg_close(&data_msg);
      continue;
    }
    std::vector<uint8_t> payload;
    payload.resize(zmq_msg_size(&data_msg));
    std::memcpy(payload.data(), zmq_msg_data(&data_msg), payload.size());
    zmq_msg_close(&data_msg);

    std::cout << "topic=" << topic
              << " size=" << payload.size()
              << " preview=" << hex_preview(payload.data(), payload.size())
              << std::endl;
  }

  zmq_close(sock);
  zmq_ctx_term(ctx);
  return 0;
}


