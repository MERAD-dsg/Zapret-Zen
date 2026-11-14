/*
 * Zapret-Zen GUI launcher (Windows, no console).
 *
 * Why this exists
 * ---------------
 * The portable distribution runs the app with the embeddable CPython
 * (`pythonw.exe -m zapret_zen.main`).  When Windows shows a taskbar button or a
 * tray balloon for that process it uses the *hosting executable* identity, so
 * users saw "Python" next to "Zapret-Zen" and a second, empty-looking console
 * window during elevation.  Shipping a real `Zapret-Zen.exe` that owns the GUI
 * window fixes both: the app process is a real Windows subsystem binary with
 * the product name, icon and AppUserModelID.
 *
 * What it does
 * ------------
 *   Zapret-Zen.exe            -> start the GUI (elevating through python.exe
 *                                only when it is needed, never lingering)
 *   Zapret-Zen.exe --uninstall-> remove firewall rule, autostart and files
 *
 * The launcher never keeps a window of its own: it resolves the bundled
 * interpreter, spawns the app and returns.  It stays alive only for the
 * elevation handshake, and only while the elevated startup is being requested.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <shlobj.h>
#include <stdbool.h>
#include <stddef.h>

#define APP_DIR_NAME L"Zapret-Zen"
#define APP_EXE_NAME L"Zapret-Zen.exe"
#define APP_TITLE L"Zapret-Zen"
#define QUIC_RULE_NAME L"Zapret-Zen QUIC block"

static wchar_t g_root[MAX_PATH];      /* directory holding this exe */
static wchar_t g_pythonw[MAX_PATH];   /* pythonw.exe */
static wchar_t g_python[MAX_PATH];    /* python.exe (elevation helper) */

static void join(wchar_t *out, const wchar_t *a, const wchar_t *b) {
    lstrcpyW(out, a);
    if (out[0] && out[lstrlenW(out) - 1] != L'\\') lstrcatW(out, L"\\");
    lstrcatW(out, b);
}

static BOOL file_exists(const wchar_t *path) {
    DWORD attrs = GetFileAttributesW(path);
    return attrs != INVALID_FILE_ATTRIBUTES && !(attrs & FILE_ATTRIBUTE_DIRECTORY);
}

static BOOL is_admin(void) {
    BOOL admin = FALSE;
    PSID group = NULL;
    SID_IDENTIFIER_AUTHORITY authority = {SECURITY_NT_AUTHORITY};
    if (AllocateAndInitializeSid(&authority, 2, SECURITY_BUILTIN_DOMAIN_RID,
                                 DOMAIN_ALIAS_RID_ADMINS, 0, 0, 0, 0, 0, 0, &group)) {
        CheckTokenMembership(NULL, group, &admin);
        FreeSid(group);
    }
    return admin;
}

static void init_paths(void) {
    DWORD len = GetModuleFileNameW(NULL, g_root, MAX_PATH);
    if (len == 0 || len >= MAX_PATH) {
        g_root[0] = 0;
        return;
    }
    for (DWORD i = len; i > 0; i--) {
        if (g_root[i - 1] == L'\\') {
            g_root[i - 1] = 0;
            break;
        }
    }
    join(g_pythonw, g_root, L"pythonw.exe");
    join(g_python, g_root, L"python.exe");
}

static void error_box(const wchar_t *text) {
    MessageBoxW(NULL, text, APP_TITLE, MB_ICONERROR | MB_OK | MB_TOPMOST);
}

/* CmdLineToArgvW-style quoting for a single argument. */
static void append_quoted(wchar_t *buffer, size_t cap, const wchar_t *arg) {
    bool needs_quotes = arg[0] == 0 || wcschr(arg, L' ') || wcschr(arg, L'\t');
    if (needs_quotes) lstrcatW(buffer, L"\"");
    lstrcatW(buffer, arg);
    if (needs_quotes) lstrcatW(buffer, L"\"");
    (void)cap;
}

/* Build "-m zapret_zen.main <forwarded args>" from our own command line. */
static void build_app_arguments(wchar_t *buffer, size_t cap) {
    buffer[0] = 0;
    lstrcatW(buffer, L"-m zapret_zen.main");
    int argc = 0;
    LPWSTR *argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argv == NULL) return;
    for (int i = 1; i < argc; i++) {
        if (argv[i][0] == 0) continue;
        /* never forward our own install/uninstall switches */
        if (lstrcmpiW(argv[i], L"--uninstall") == 0) continue;
        if (lstrcmpiW(argv[i], L"/uninstall") == 0) continue;
        if (lstrcmpiW(argv[i], L"--silent") == 0) continue;
        lstrcatW(buffer, L" ");
        append_quoted(buffer, cap, argv[i]);
    }
    LocalFree(argv);
}

/* Spawn pythonw.exe without a console, inheriting our environment. */
static BOOL spawn_hidden(const wchar_t *exe, const wchar_t *args, PROCESS_INFORMATION *pi) {
    STARTUPINFOW si;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;

    size_t cap = lstrlenW(exe) + lstrlenW(args) + 8;
    wchar_t *cmd = (wchar_t *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, cap * sizeof(wchar_t));
    if (cmd == NULL) return FALSE;
    lstrcpyW(cmd, L"\"");
    lstrcatW(cmd, exe);
    lstrcatW(cmd, L"\" ");
    lstrcatW(cmd, args);

    BOOL ok = CreateProcessW(exe, cmd, NULL, NULL, FALSE, CREATE_UNICODE_ENVIRONMENT,
                             NULL, g_root, &si, pi);
    HeapFree(GetProcessHeap(), 0, cmd);
    return ok;
}

/* Ask the shell for elevation *without* keeping an extra process around. */
static BOOL elevate_and_wait(const wchar_t *exe, const wchar_t *args, DWORD timeout_ms) {
    SHELLEXECUTEINFOW info;
    ZeroMemory(&info, sizeof(info));
    info.cbSize = sizeof(info);
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC | SEE_MASK_FLAG_NO_UI;
    info.lpVerb = L"runas";
    info.lpFile = exe;
    info.lpParameters = args;
    info.lpDirectory = g_root;
    info.nShow = SW_HIDE;
    if (!ShellExecuteExW(&info)) {
        DWORD code = GetLastError();
        if (code == ERROR_CANCELLED) return TRUE; /* user declined: stay silent */
        return FALSE;
    }
    if (info.hProcess != NULL) {
        WaitForSingleObject(info.hProcess, timeout_ms);
        CloseHandle(info.hProcess);
    }
    return TRUE;
}

static void remove_quic_rule(void) {
    wchar_t cmd[512];
    lstrcpyW(cmd, L"advfirewall firewall delete rule name=\"");
    lstrcatW(cmd, QUIC_RULE_NAME);
    lstrcatW(cmd, L"\"");
    PROCESS_INFORMATION pi;
    /* PowerShell-free, hidden, fire and forget. */
    size_t cap = lstrlenW(cmd) + 32;
    wchar_t *full = (wchar_t *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, cap * sizeof(wchar_t));
    if (full == NULL) return;
    lstrcpyW(full, L"netsh ");
    lstrcatW(full, cmd);
    STARTUPINFOW si;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    if (CreateProcessW(NULL, full, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi)) {
        WaitForSingleObject(pi.hProcess, 5000);
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
    }
    HeapFree(GetProcessHeap(), 0, full);
}

static void remove_autostart(void) {
    HKEY key;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, L"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                      0, KEY_SET_VALUE, &key) == ERROR_SUCCESS) {
        RegDeleteValueW(key, L"ZapretZen");
        RegDeleteValueW(key, L"Zapret-Zen");
        RegCloseKey(key);
    }
}

/*
 * The uninstaller cannot delete the folder it runs from, so it kills the
 * remaining processes (winws, the app) and hands the folder removal to a
 * detached cmd.exe that waits, then removes the directory.
 */
static void remove_install_dir(void) {
    wchar_t cmd[MAX_PATH * 2];
    lstrcpyW(cmd, L"/C timeout /t 2 >NUL & taskkill /IM winws.exe /F >NUL 2>&1 & rmdir /S /Q \"");
    lstrcatW(cmd, g_root);
    lstrcatW(cmd, L"\"");
    PROCESS_INFORMATION pi;
    STARTUPINFOW si;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    if (CreateProcessW(NULL, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi)) {
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
    }
}

static int run_uninstall(void) {
    if (!is_admin()) {
        wchar_t self[MAX_PATH];
        DWORD len = GetModuleFileNameW(NULL, self, MAX_PATH);
        if (len == 0 || len >= MAX_PATH) return 1;
        if (!elevate_and_wait(self, L"--uninstall", 30000)) return 1;
        return 0;
    }
    remove_autostart();
    remove_quic_rule();
    remove_install_dir();
    return 0;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR cmdline, int show) {
    (void)instance; (void)previous; (void)cmdline; (void)show;
    init_paths();
    if (g_root[0] == 0) {
        error_box(L"Не удалось определить папку программы.");
        return 1;
    }
    if (!file_exists(g_pythonw)) {
        wchar_t message[MAX_PATH * 2];
        lstrcpyW(message, L"Не найден pythonw.exe рядом с ");
        lstrcatW(message, APP_EXE_NAME);
        lstrcatW(message, L".\nРаспакуйте архив полностью, не запускайте файл из ZIP.");
        error_box(message);
        return 2;
    }

    int argc = 0;
    LPWSTR *argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    BOOL want_uninstall = FALSE;
    if (argv != NULL) {
        for (int i = 1; i < argc; i++) {
            if (lstrcmpiW(argv[i], L"--uninstall") == 0 || lstrcmpiW(argv[i], L"/uninstall") == 0)
                want_uninstall = TRUE;
        }
        LocalFree(argv);
    }
    if (want_uninstall) return run_uninstall();

    wchar_t args[8192];
    build_app_arguments(args, 8192);

    PROCESS_INFORMATION pi;
    ZeroMemory(&pi, sizeof(pi));
    /* pythonw.exe has no console, so no extra black window can appear next to
     * the main window (the old .cmd launcher used python.exe and left one).
     * The application raises its own UAC prompt via ShellExecuteW("runas")
     * when it needs WinDivert, so we deliberately do not elevate here: an
     * unelevated launcher exits immediately and leaves nothing behind. */
    if (!spawn_hidden(g_pythonw, args, &pi)) {
        error_box(L"Не удалось запустить Zapret-Zen (pythonw.exe).\nПереустановите программу или запустите run_zapret_zen.cmd для диагностики.");
        return 3;
    }
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return 0;
}
