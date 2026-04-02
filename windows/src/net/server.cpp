#include "net/server.h"

#include "logger.h"
#include "adb.h"
#include "net/serializer.h"

Server::Server(int port, const ConnectionListener& connectionListener) :
	port(port),
	connectionListener(connectionListener),
	acceptor(context)
{
	try {
		tcp::endpoint endpoint(tcp::v4(), port);
		acceptor.open(endpoint.protocol());

		acceptor.set_option(tcp::acceptor::reuse_address(true));

		acceptor.bind(endpoint);
		acceptor.listen();

		logger << "[SERVER] Initialized on port " << port << std::endl;
		
		adb::reverse(port);
		adb::forward(8554);
	}
	catch(std::exception& e)
	{
		logger << "[SERVER] CRITICAL INIT ERROR: " << e.what() << std::endl;
		throw;
	}
}

Server::HostInfo Server::GetHostInfo()
{
	std::string name = asio::ip::host_name();
	std::string ip_str = "127.0.0.1"; // Default fallback

	try {
		// Get the active network adapter by creating a dummy UDP connection 
		// and let the OS determine what network adapter will be used
		udp::resolver resolver(context);
		udp::socket socket(context);

		// This might throw if there is NO network adapter enabled
		socket.connect(udp::endpoint(asio::ip::address::from_string("8.8.8.8"), 80));
		ip_str = socket.local_endpoint().address().to_string();
		socket.close();
	}
	catch (std::exception& e) 
	{
		logger << "[SERVER] Warning: Could not detect local IP (" << e.what() << "). Defaulting to localhost.\n";
	}

	return { name, ip_str, std::to_string(port) };
}

void Server::Send(int id, const unsigned char* bytes, size_t size) const
{
	if (id >= 0 && id < connections.size())
	{
		connections[id]->Send(bytes, size);
	}
}

void Server::Start()
{
	if (!acceptor.is_open()) 
	{
		logger << "[SERVER] Cannot start: Acceptor is not open.\n";
		return;
	}

	try
	{
		TCPDoAccept();

		thread = std::thread([this]() {
			while (true)
			{
				try {
					context.run();
					break;
				}
				catch (std::exception& e) {
					logger << "[SERVER] CRITICAL EXCEPTION in IO Thread: " << e.what() << std::endl;
				}
				catch (...) {
					logger << "[SERVER] Unknown exception in IO Thread.\n";
				}
			}
		});
		
		logger << "[SERVER] Started" << std::endl;
	}
	catch (std::exception e)
	{
		logger << "[SERVER] Start failed: " << e.what() << "\n";
	}
}

void Server::Close()
{
	logger << "[SERVER] Closing...\n";

	asio::error_code ec;
	acceptor.close(ec);
	if (ec) logger << "[SERVER] Error closing acceptor: " << ec.message() << "\n";
	
	for (std::shared_ptr<Connection> conn : connections)
	{
		conn->Close(true);
	}

	context.stop();

	if (thread.joinable())
	{
		thread.join();
	}

	logger << "[SERVER] Closed.\n";

	adb::kill(port);
}

void Server::TCPDoAccept()
{
	acceptor.async_accept([&, this](asio::error_code ec, tcp::socket socket) {
		if (!ec)
		{
			logger << "[SERVER] Device connected." << socket.remote_endpoint() << std::endl;

			// Read the only message sent by the client (the device descriptor)
			// We need to read this here because the connection listener
			// needs all the data sent by the client (trough GetConnectedDevicesInfo)
			// otherwise the connection would need to be passed to the connection
			std::vector<uint8_t> buffer;
			std::array<uint8_t, 1024> chunk;
			asio::error_code readEc;
			size_t n;
			do {
				n = socket.read_some(asio::buffer(chunk), readEc);
				if (n > 0) buffer.insert(buffer.end(), chunk.begin(), chunk.begin() + n);
			} while (n == chunk.size() && !readEc);

			// auto ipaddress = socket.remote_endpoint().address().to_string();
			auto descriptor = Serializer::DeserializeDeviceDescriptor(buffer.data(), buffer.size());

			auto conn = std::make_shared<Connection>(
				std::move(socket),
				descriptor,
				std::bind(&Server::OnConnectionDisconnected, this, std::placeholders::_1),
				std::bind(&Server::OnConnectionReportingError, this, std::placeholders::_1, std::placeholders::_2, std::placeholders::_3)
			);
			connections.push_back(std::move(conn));

			connectionListener.OnDeviceConnected(descriptor);
		}
		else if (ec != asio::error::operation_aborted)
		{
			logger << "[SERVER] Accept Error: " << ec.message() << std::endl;
		}

		if (acceptor.is_open()) {
			TCPDoAccept();
		}
	});
}

void Server::OnConnectionDisconnected(std::shared_ptr<Connection> connection)
{
	logger << "[SERVER] Device disconnected: " << connection->descriptor.name() << std::endl;

	connections.erase(std::remove(connections.begin(), connections.end(), connection), connections.end());
	connectionListener.OnDeviceDisconnected(connection->descriptor);
}

void Server::OnConnectionReportingError(std::shared_ptr<Connection> connection, const uint8_t* bytes, size_t size)
{
	auto report = Serializer::DeserializeErrorReport(bytes, size);
	connectionListener.OnDeviceErrorReported(connection->descriptor, report);
}
