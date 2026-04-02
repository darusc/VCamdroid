#pragma once

#include <windows.h>
#include <dbghelp.h>
#include <ctime>
#include <exception>
#include <string>

#pragma comment(lib, "dbghelp.lib")

#include "logger.h"

extern Logger logger;

namespace CrashHandler
{
	static std::string TimestampedDumpPath()
	{
		time_t now = time(nullptr);
		char buf[64];
		struct tm tm_info;
		localtime_s(&tm_info, &now);
		strftime(buf, sizeof(buf), "vcamdroid_crash_%Y%m%d_%H%M%S.dmp", &tm_info);
		return buf;
	}

	static void WriteDump(EXCEPTION_POINTERS* exceptionInfo = nullptr)
	{
		std::string path = TimestampedDumpPath();

		HANDLE hFile = CreateFileA(path.c_str(), GENERIC_WRITE, 0, nullptr,
			CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);

		if (hFile == INVALID_HANDLE_VALUE)
		{
			logger << "[CRASH] Failed to create dump file: " << path << "\n";
			return;
		}

		MINIDUMP_EXCEPTION_INFORMATION info{};
		MINIDUMP_EXCEPTION_INFORMATION* pInfo = nullptr;
		if (exceptionInfo)
		{
			info.ThreadId = GetCurrentThreadId();
			info.ExceptionPointers = exceptionInfo;
			info.ClientPointers = TRUE;
			pInfo = &info;
		}

		MiniDumpWriteDump(GetCurrentProcess(), GetCurrentProcessId(), hFile,
			MiniDumpWithThreadInfo, pInfo, nullptr, nullptr);
		CloseHandle(hFile);

		logger << "[CRASH] Minidump written: " << path << "\n";
	}

	static LONG WINAPI ExceptionFilter(EXCEPTION_POINTERS* exceptionInfo)
	{
		DWORD code = exceptionInfo->ExceptionRecord->ExceptionCode;
		auto addr = reinterpret_cast<uintptr_t>(exceptionInfo->ExceptionRecord->ExceptionAddress);

		logger << "[CRASH] Unhandled exception - code: 0x" << std::hex << code
			<< "  address: 0x" << addr << std::dec << "\n";

		WriteDump(exceptionInfo);

		return EXCEPTION_EXECUTE_HANDLER;
	}

	static void TerminateHandler()
	{
		logger << "[CRASH] std::terminate() called - unhandled C++ exception\n";
		WriteDump();
	}

	static void Install()
	{
		SetUnhandledExceptionFilter(ExceptionFilter);
		std::set_terminate(TerminateHandler);
	}
}
