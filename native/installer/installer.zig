//! Zapret-Zen installer — self-contained Windows GUI (x64 / arm64).
//!
//! Cross-compiled by `scripts/build_installer.py` (Zig 0.17, no Windows SDK
//! needed), so the Windows artefacts can be produced from any Linux/CI host.
//!
//! Two payload modes:
//!   * `payload.zip` embedded (`-Dembed_zip=1`)  -> single setup .exe
//!   * `payload.zip` / `Zapret-Zen-portable.zip` next to the installer
//!
//! What it does
//!   1. extracts the portable tree into %ProgramFiles%\Zapret-Zen (no per-file
//!      MSI magic, the in-app updater keeps working),
//!   2. creates a Start-menu shortcut pointing at `Zapret-Zen.exe`,
//!   3. registers an uninstall entry whose command is `Zapret-Zen.exe --uninstall`
//!      (the launcher removes the firewall rule, autostart and files),
//!   4. optionally launches the app.
//!
//! No console window is ever created (GUI subsystem) and no helper process is
//! left behind after installation.
const std = @import("std");
const builtin = @import("builtin");

const build_options = @import("build_options");

const Options = struct {
    embed: bool = false,
    version: []const u8 = "2.2.0",
    ascii: bool = false,
};

const opts: Options = .{
    .embed = @hasDecl(build_options, "embed_payload") and build_options.embed_payload,
    .version = if (@hasDecl(build_options, "app_version")) build_options.app_version else "2.2.0",
    .ascii = @hasDecl(build_options, "ascii_ui") and build_options.ascii_ui,
};

const payload_module = @import("payload");

const payload_bytes: []const u8 = if (opts.embed)
    payload_module.bytes
else
    "";

const win = struct {
    const HINSTANCE = *anyopaque;
    const HWND = *anyopaque;
    const HKEY = *anyopaque;
    const HMODULE = *anyopaque;
    const HGLOBAL = *anyopaque;
    const HANDLE = *anyopaque;
    const HBRUSH = *anyopaque;
    const HFONT = *anyopaque;
    const LRESULT = isize;
    const LPARAM = isize;
    const WPARAM = usize;
    const UINT = c_uint;
    const DWORD = c_uint;
    const BOOL = c_int;
    const HRESULT = c_long;
    const WNDPROC = *const fn (HWND, UINT, WPARAM, LPARAM) callconv(.winapi) LRESULT;

    const WNDCLASSEXW = extern struct {
        cbSize: UINT = @sizeOf(WNDCLASSEXW),
        style: UINT = 0,
        lpfnWndProc: ?WNDPROC = null,
        cbClsExtra: c_int = 0,
        cbWndExtra: c_int = 0,
        hInstance: ?HINSTANCE = null,
        hIcon: ?HANDLE = null,
        hCursor: ?HANDLE = null,
        hbrBackground: ?HBRUSH = null,
        lpszMenuName: ?[*:0]const u16 = null,
        lpszClassName: ?[*:0]const u16 = null,
        hIconSm: ?HANDLE = null,
    };

    const POINT = extern struct { x: c_long = 0, y: c_long = 0 };
    const MSG = extern struct {
        hwnd: ?HWND = null,
        message: UINT = 0,
        wParam: WPARAM = 0,
        lParam: LPARAM = 0,
        time: DWORD = 0,
        pt: POINT = .{},
    };
    const RECT = extern struct { left: c_long = 0, top: c_long = 0, right: c_long = 0, bottom: c_long = 0 };
    const PAINTSTRUCT = extern struct {
        hdc: ?HANDLE = null,
        fErase: BOOL = 0,
        rcPaint: RECT = .{},
        fRestore: BOOL = 0,
        fIncUpdate: BOOL = 0,
        rgbReserved: [32]u8 = @splat(0),
    };
    const STARTUPINFOW = extern struct {
        cb: DWORD = @sizeOf(STARTUPINFOW),
        lpReserved: ?[*:0]u16 = null,
        lpDesktop: ?[*:0]u16 = null,
        lpTitle: ?[*:0]u16 = null,
        dwX: DWORD = 0,
        dwY: DWORD = 0,
        dwXSize: DWORD = 0,
        dwYSize: DWORD = 0,
        dwXCountChars: DWORD = 0,
        dwYCountChars: DWORD = 0,
        dwFillAttribute: DWORD = 0,
        dwFlags: DWORD = 0,
        wShowWindow: u16 = 0,
        cbReserved2: u16 = 0,
        lpReserved2: ?*u8 = null,
        hStdInput: ?HANDLE = null,
        hStdOutput: ?HANDLE = null,
        hStdError: ?HANDLE = null,
    };
    const PROCESS_INFORMATION = extern struct {
        hProcess: ?HANDLE = null,
        hThread: ?HANDLE = null,
        dwProcessId: DWORD = 0,
        dwThreadId: DWORD = 0,
    };

    pub extern "user32" fn RegisterClassExW(*const WNDCLASSEXW) callconv(.winapi) u16;
    pub extern "user32" fn CreateWindowExW(DWORD, [*:0]const u16, [*:0]const u16, DWORD, c_int, c_int, c_int, c_int, ?HWND, ?HANDLE, ?HINSTANCE, ?*anyopaque) callconv(.winapi) ?HWND;
    pub extern "user32" fn DefWindowProcW(HWND, UINT, WPARAM, LPARAM) callconv(.winapi) LRESULT;
    pub extern "user32" fn DestroyWindow(HWND) callconv(.winapi) BOOL;
    pub extern "user32" fn PostQuitMessage(c_int) callconv(.winapi) void;
    pub extern "user32" fn PostMessageW(?HWND, UINT, WPARAM, LPARAM) callconv(.winapi) BOOL;
    pub extern "user32" fn GetMessageW(*MSG, ?HWND, UINT, UINT) callconv(.winapi) BOOL;
    pub extern "user32" fn TranslateMessage(*const MSG) callconv(.winapi) BOOL;
    pub extern "user32" fn DispatchMessageW(*const MSG) callconv(.winapi) LRESULT;
    pub extern "user32" fn SendMessageW(HWND, UINT, WPARAM, LPARAM) callconv(.winapi) LRESULT;
    pub extern "user32" fn SetWindowTextW(HWND, [*:0]const u16) callconv(.winapi) BOOL;
    pub extern "user32" fn ShowWindow(HWND, c_int) callconv(.winapi) BOOL;
    pub extern "user32" fn UpdateWindow(HWND) callconv(.winapi) BOOL;
    pub extern "user32" fn EnableWindow(HWND, BOOL) callconv(.winapi) BOOL;
    pub extern "user32" fn GetSystemMetrics(c_int) callconv(.winapi) c_int;
    pub extern "user32" fn MessageBoxW(?HWND, [*:0]const u16, [*:0]const u16, UINT) callconv(.winapi) c_int;
    pub extern "user32" fn BeginPaint(HWND, *PAINTSTRUCT) callconv(.winapi) ?HANDLE;
    pub extern "user32" fn EndPaint(HWND, *const PAINTSTRUCT) callconv(.winapi) BOOL;
    pub extern "user32" fn FillRect(?HANDLE, *const RECT, ?HBRUSH) callconv(.winapi) c_int;
    pub extern "user32" fn CreateSolidBrush(DWORD) callconv(.winapi) HBRUSH;
    pub extern "user32" fn DeleteObject(?HANDLE) callconv(.winapi) BOOL;
    pub extern "user32" fn DrawTextW(?HANDLE, [*]const u16, c_int, *RECT, UINT) callconv(.winapi) c_int;
    pub extern "user32" fn GetClientRect(HWND, *RECT) callconv(.winapi) BOOL;
    pub extern "user32" fn InvalidateRect(HWND, ?*const RECT, BOOL) callconv(.winapi) BOOL;
    pub extern "user32" fn LoadImageW(?HINSTANCE, ?*const anyopaque, UINT, c_int, c_int, UINT) callconv(.winapi) ?HANDLE;
    pub extern "user32" fn LoadCursorW(?HINSTANCE, ?*const anyopaque) callconv(.winapi) ?HANDLE;
    pub extern "user32" fn LoadIconW(?HINSTANCE, ?*const anyopaque) callconv(.winapi) ?HANDLE;
    pub extern "user32" fn SetCursor(?HANDLE) callconv(.winapi) ?HANDLE;
    pub extern "user32" fn GetStockObject(c_int) callconv(.winapi) ?HANDLE;

    pub extern "gdi32" fn CreateFontW(c_int, c_int, c_int, c_int, c_int, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, [*:0]const u16) callconv(.winapi) ?HFONT;
    pub extern "gdi32" fn SelectObject(?HANDLE, ?HANDLE) callconv(.winapi) ?HANDLE;
    pub extern "gdi32" fn SetTextColor(?HANDLE, DWORD) callconv(.winapi) DWORD;
    pub extern "gdi32" fn SetBkMode(?HANDLE, c_int) callconv(.winapi) c_int;
    pub extern "gdi32" fn SetBkColor(?HANDLE, DWORD) callconv(.winapi) DWORD;

    pub extern "shell32" fn ShellExecuteW(?HWND, [*:0]const u16, [*:0]const u16, ?[*:0]const u16, ?[*:0]const u16, c_int) callconv(.winapi) ?HANDLE;
    pub extern "shell32" fn SHGetFolderPathW(?HWND, c_int, ?HANDLE, DWORD, [*]u16) callconv(.winapi) HRESULT;
    pub extern "shell32" fn SHGetKnownFolderPath(*const GUID, DWORD, ?HANDLE, *[*:0]u16) callconv(.winapi) HRESULT;

    pub const GUID = extern struct { data1: u32, data2: u16, data3: u16, data4: [8]u8 };

    pub extern "ole32" fn CoInitializeEx(?*anyopaque, DWORD) callconv(.winapi) HRESULT;
    pub extern "ole32" fn CoCreateInstance(*const GUID, ?*anyopaque, DWORD, *const GUID, *?*anyopaque) callconv(.winapi) HRESULT;
    pub extern "ole32" fn CoUninitialize() callconv(.winapi) void;

    pub extern "advapi32" fn RegCreateKeyExW(HKEY, [*:0]const u16, DWORD, ?[*:0]const u16, DWORD, DWORD, ?*anyopaque, *HKEY, ?*DWORD) callconv(.winapi) c_long;
    pub extern "advapi32" fn RegSetValueExW(HKEY, [*:0]const u16, DWORD, DWORD, [*]const u8, DWORD) callconv(.winapi) c_long;
    pub extern "advapi32" fn RegCloseKey(HKEY) callconv(.winapi) c_long;

    pub extern "kernel32" fn GetModuleHandleW(?[*:0]const u16) callconv(.winapi) ?HMODULE;
    pub extern "kernel32" fn GetModuleFileNameW(?HMODULE, [*]u16, DWORD) callconv(.winapi) DWORD;
    pub extern "kernel32" fn GetCommandLineW() callconv(.winapi) [*:0]const u16;
    pub extern "kernel32" fn CreateProcessW(?[*:0]const u16, [*:0]u16, ?*anyopaque, ?*anyopaque, BOOL, DWORD, ?*anyopaque, ?[*:0]const u16, *STARTUPINFOW, *PROCESS_INFORMATION) callconv(.winapi) BOOL;
    pub extern "kernel32" fn WaitForSingleObject(?HANDLE, DWORD) callconv(.winapi) DWORD;
    pub extern "kernel32" fn CloseHandle(?HANDLE) callconv(.winapi) BOOL;
    pub extern "kernel32" fn GetFileAttributesW([*:0]const u16) callconv(.winapi) DWORD;
    pub extern "kernel32" fn GetTempPathW(DWORD, [*]u16) callconv(.winapi) DWORD;
    pub extern "kernel32" fn CreateDirectoryW([*:0]const u16, ?*anyopaque) callconv(.winapi) BOOL;
};

// ---- Win32 constants -------------------------------------------------------
const WS_OVERLAPPED: u32 = 0x00000000;
const WS_CAPTION: u32 = 0x00C00000;
const WS_SYSMENU: u32 = 0x00080000;
const WS_MINIMIZEBOX: u32 = 0x00020000;
const WS_CHILD: u32 = 0x40000000;
const WS_VISIBLE: u32 = 0x10000000;
const WS_TABSTOP: u32 = 0x00010000;
const WS_BORDER: u32 = 0x00800000;
const BS_PUSHBUTTON: u32 = 0x00000000;
const BS_AUTOCHECKBOX: u32 = 0x00000003;
const BM_SETCHECK: u32 = 0x00F1;
const BM_GETCHECK: u32 = 0x00F0;
const BST_CHECKED: isize = 1;
const SS_LEFT: u32 = 0x00000000;
const ES_AUTOHSCROLL: u32 = 0x0080;
const ES_READONLY: u32 = 0x0800;
const WM_CREATE: u32 = 0x0001;
const WM_DESTROY: u32 = 0x0002;
const WM_CLOSE: u32 = 0x0010;
const WM_COMMAND: u32 = 0x0111;
const WM_PAINT: u32 = 0x000F;
const WM_SETFONT: u32 = 0x0030;
const WM_APP: u32 = 0x8000;
const WM_USER: u32 = 0x0400;
const SW_SHOW: c_int = 5;
const SW_HIDE: c_int = 0;
const SW_SHOWNORMAL: c_int = 1;
const STARTF_USESHOWWINDOW: u32 = 0x00000001;
const CREATE_NO_WINDOW: u32 = 0x08000000;
const DT_LEFT: u32 = 0x0000;
const DT_WORDBREAK: u32 = 0x0010;
const DT_SINGLELINE: u32 = 0x0020;
const DT_NOPREFIX: u32 = 0x0800;
const TRANSPARENT: c_int = 1;
const CSIDL_PROGRAM_FILES: c_int = 0x0026;
const HKEY_CURRENT_USER: win.HKEY = @ptrFromInt(0x80000001);
const KEY_WRITE: u32 = 0x20006;
const REG_SZ: u32 = 1;
const REG_DWORD: u32 = 4;
const IDC_ARROW: usize = 32512;
const IMAGE_CURSOR: u32 = 2;
const LR_SHARED: u32 = 0x00008000;
const CLSCTX_INPROC_SERVER: u32 = 0x1;

const ID_INSTALL: usize = 1001;
const ID_CANCEL: usize = 1002;
const ID_LAUNCH: usize = 1003;
const ID_PATH: usize = 1004;
const WM_PROGRESS: u32 = WM_APP + 1;
const WM_FINISHED: u32 = WM_APP + 2;
const WM_FAILED: u32 = WM_APP + 3;

// Colours (COLORREF is 0x00BBGGRR)
const C_BG: u32 = 0x00F7F3EE; // very light warm grey
const C_CARD: u32 = 0x00FFFFFF;
const C_TEXT: u32 = 0x001E1408;
const C_MUTED: u32 = 0x00786452;
const C_ACCENT: u32 = 0x00D9622E; // blue-ish accent (BGR): #2E62D9
const C_TRACK: u32 = 0x00E7E0D7;

var g_hwnd: ?win.HWND = null;
var g_install_btn: ?win.HWND = null;
var g_cancel_btn: ?win.HWND = null;
var g_launch_box: ?win.HWND = null;
var g_status: ?win.HWND = null;
var g_path: ?win.HWND = null;
var g_font_body: ?win.HFONT = null;
var g_font_title: ?win.HFONT = null;
var g_font_small: ?win.HFONT = null;
var g_bg_brush: ?win.HBRUSH = null;
var g_card_brush: ?win.HBRUSH = null;
var g_track_brush: ?win.HBRUSH = null;
var g_accent_brush: ?win.HBRUSH = null;

var g_state: enum { idle, working, done, failed } = .idle;
var g_progress: f32 = 0.0;
var g_silent = false;
var g_error_text: []const u8 = "";
var g_install_dir: std.ArrayListUnmanaged(u16) = .empty;
var g_exe_dir: std.ArrayListUnmanaged(u16) = .empty;
// UTF-8 mirrors for std.Io file operations (Win32 calls use the UTF-16 forms).
var g_install_utf8: []const u8 = "";
var g_exe_dir_utf8: []const u8 = "";
var g_gpa: std.mem.Allocator = undefined;
var g_io: std.Io = undefined;
var g_threaded: std.Io.Threaded = undefined;
var g_arena: std.heap.ArenaAllocator = undefined;

fn wide(text: []const u8) [:0]const u16 {
    return std.unicode.utf8ToUtf16LeAllocZ(g_gpa, text) catch @panic("oom");
}

fn set_control_text(hwnd: ?win.HWND, text: []const u8) void {
    const target = hwnd orelse return;
    var buf: [2048]u16 = undefined;
    const n = std.unicode.utf8ToUtf16Le(buf[0..], text) catch return;
    buf[n] = 0;
    _ = win.SetWindowTextW(target, buf[0..n :0].ptr);
}

fn message_box(text: []const u8, flags: u32) void {
    const t = wide(text);
    defer g_gpa.free(t);
    const title = wide("Zapret-Zen");
    defer g_gpa.free(title);
    _ = win.MessageBoxW(null, t.ptr, title.ptr, flags);
}

fn utf16_buf(list: std.ArrayListUnmanaged(u16)) []const u16 {
    return list.items;
}

fn dir_to_z(list: std.ArrayListUnmanaged(u16)) [:0]const u16 {
    // Callers keep the backing list alive for the process lifetime.
    const copy = g_gpa.allocSentinel(u16, list.items.len, 0) catch @panic("oom");
    @memcpy(copy[0..list.items.len], list.items);
    return copy;
}

fn append_utf8(list: *std.ArrayListUnmanaged(u16), text: []const u8) !void {
    const len = std.unicode.calcUtf16LeLen(text) catch return error.InvalidUtf8;
    const old = list.items.len;
    try list.resize(g_gpa, old + len);
    _ = try std.unicode.utf8ToUtf16Le(list.items[old..], text);
}

fn file_exists(path: [:0]const u16) bool {
    return win.GetFileAttributesW(path.ptr) != 0xFFFFFFFF;
}

fn compute_paths() !void {
    const module = win.GetModuleHandleW(null) orelse return error.NoModule;
    var buf: [32768]u16 = undefined;
    const n = win.GetModuleFileNameW(module, &buf, buf.len);
    if (n == 0 or n >= buf.len) return error.NameTooLong;
    try g_exe_dir.appendSlice(g_gpa, buf[0..n]);
    var cut = g_exe_dir.items.len;
    while (cut > 0 and g_exe_dir.items[cut - 1] != '\\') : (cut -= 1) {}
    if (cut > 0) cut -= 1;
    g_exe_dir.shrinkRetainingCapacity(cut);

    var program_files: [32768]u16 = undefined;
    program_files[0] = 0;
    _ = win.SHGetFolderPathW(null, CSIDL_PROGRAM_FILES, null, 0, &program_files);
    var len: usize = 0;
    while (program_files[len] != 0) : (len += 1) {}
    if (len == 0) {
        try g_install_dir.appendSlice(g_gpa, g_exe_dir.items);
        try append_utf8(&g_install_dir, "\\Zapret-Zen");
    } else {
        try g_install_dir.appendSlice(g_gpa, program_files[0..len]);
        try append_utf8(&g_install_dir, "\\Zapret-Zen");
    }
    g_install_utf8 = try std.unicode.utf16LeToUtf8Alloc(g_gpa, g_install_dir.items);
    g_exe_dir_utf8 = try std.unicode.utf16LeToUtf8Alloc(g_gpa, g_exe_dir.items);
}

/// Copy of the payload next to the installer or into %TEMP% (embedded build).
fn materialise_payload() anyerror![]const u8 {
    if (opts.embed) {
        var temp: [32768]u16 = undefined;
        const n = win.GetTempPathW(temp.len, &temp);
        if (n == 0) return error.NoTemp;
        const temp_utf8 = try std.unicode.utf16LeToUtf8Alloc(g_gpa, temp[0..n]);
        const path = try std.fmt.allocPrint(g_gpa, "{s}zapret-zen-payload-{s}.zip", .{ temp_utf8, opts.version });
        const file = try std.Io.Dir.cwd().createFile(g_io, path, .{ .truncate = true });
        defer file.close(g_io);
        var buf: [64 * 1024]u8 = undefined;
        var writer = file.writer(g_io, &buf);
        try writer.interface.writeAll(payload_bytes);
        try writer.interface.flush();
        return path;
    }
    const candidates = [_][]const u8{ "\\payload.zip", "\\Zapret-Zen-portable.zip" };
    for (candidates) |name| {
        const path = try std.fmt.allocPrint(g_gpa, "{s}{s}", .{ g_exe_dir_utf8, name });
        var dir = std.Io.Dir.cwd().openDir(g_io, g_exe_dir_utf8, .{}) catch continue;
        dir.close(g_io);
        std.Io.Dir.cwd().access(g_io, path, .{}) catch continue;
        return path;
    }
    return error.PayloadMissing;
}

fn dir_exists(path: []const u8) bool {
    var dir = std.Io.Dir.cwd().openDir(g_io, path, .{}) catch return false;
    dir.close(g_io);
    return true;
}

fn dir_is_empty(path: []const u8) bool {
    var dir = std.Io.Dir.cwd().openDir(g_io, path, .{}) catch return true;
    defer dir.close(g_io);
    var iterator = dir.iterate();
    const entry = iterator.next(g_io) catch return false;
    return entry == null;
}

fn clear_previous_install() void {
    // Only touch a directory that is either empty or a previous Zapret-Zen
    // install (recognisable by pythonw.exe / Zapret-Zen.exe).  Anything else is
    // left alone so the installer can never delete unrelated files.
    if (!dir_exists(g_install_utf8)) return;
    const looks_like_previous = looks_like_zapret_install(g_install_utf8);
    if (!looks_like_previous and !dir_is_empty(g_install_utf8)) {
        set_control_text(g_status, "В папке установки уже есть посторонние файлы — распаковка поверх.");
        remove_nested_payload_dirs(g_install_utf8);
        return;
    }
    if (looks_like_previous) {
        set_control_text(g_status, "Удаление предыдущей версии…");
        std.Io.Dir.cwd().deleteTree(g_io, g_install_utf8) catch {};
        return;
    }
    // 2.1f extracted the archive verbatim, leaving the payload one level deeper
    // ("...\\Zapret-Zen\\Zapret-Zen-2.1f-portable\\Zapret-Zen.exe").  Remove such
    // nested copies so the fixed layout is what ends up on disk.
    remove_nested_payload_dirs(g_install_utf8);
}

fn remove_nested_payload_dirs(root: []const u8) void {
    var dir = std.Io.Dir.cwd().openDir(g_io, root, .{}) catch return;
    defer dir.close(g_io);
    var iterator = dir.iterate();
    while (iterator.next(g_io) catch null) |entry| {
        if (entry.kind != .directory) continue;
        if (!std.mem.startsWith(u8, entry.name, "Zapret-Zen-")) continue;
        const nested = std.fmt.allocPrint(g_gpa, "{s}\\{s}", .{ root, entry.name }) catch continue;
        if (!looks_like_zapret_install(nested)) continue;
        set_control_text(g_status, "Удаление остатков предыдущей версии…");
        std.Io.Dir.cwd().deleteTree(g_io, nested) catch {};
    }
}

fn looks_like_zapret_install(path: []const u8) bool {
    const markers = [_][]const u8{ "\\Zapret-Zen.exe", "\\pythonw.exe", "\\python311.dll" };
    for (markers) |marker| {
        const candidate = std.fmt.allocPrint(g_gpa, "{s}{s}", .{ path, marker }) catch continue;
        std.Io.Dir.cwd().access(g_io, candidate, .{}) catch continue;
        return true;
    }
    return false;
}

fn set_progress(value: f32) void {
    g_progress = std.math.clamp(value, 0.0, 1.0);
    if (g_hwnd) |hwnd| _ = win.InvalidateRect(hwnd, null, 0);
}

fn extract_all(payload: []const u8, dest: []const u8) !void {
    var dir = try std.Io.Dir.cwd().createDirPathOpen(g_io, dest, .{});
    defer dir.close(g_io);

    const file = try std.Io.Dir.cwd().openFile(g_io, payload, .{});
    defer file.close(g_io);
    var read_buf: [128 * 1024]u8 = undefined;
    var reader = file.reader(g_io, &read_buf);

    var iterator = try std.zip.Iterator.init(&reader);
    var filename_buf: [std.fs.max_path_bytes]u8 = undefined;
    const total = @max(iterator.cd_record_count, 1);
    var index: u64 = 0;
    // The portable archive wraps everything in a single top-level folder
    // ("Zapret-Zen-2.1f-portable/").  Extracting it verbatim used to install
    // the app as %ProgramFiles%\Zapret-Zen\Zapret-Zen-2.1f-portable\..., which
    // broke shortcut targets and the uninstaller, so that prefix is stripped.
    var prefix_buf: [512]u8 = undefined;
    var prefix_len: usize = 0;
    var prefix_known = false;
    while (try iterator.next()) |entry| {
        const name = try entry.getFilename(&reader, &filename_buf, .{ .allow_backslashes = true });
        var relative = name;
        if (!prefix_known) {
            prefix_known = true;
            if (std.mem.indexOfScalar(u8, name, '/')) |slash| {
                prefix_len = @min(slash + 1, prefix_buf.len);
                @memcpy(prefix_buf[0..prefix_len], name[0..prefix_len]);
            }
        }
        if (prefix_len > 0 and relative.len >= prefix_len and std.mem.eql(u8, relative[0..prefix_len], prefix_buf[0..prefix_len])) {
            relative = relative[prefix_len..];
        }
        if (relative.len == 0) continue;
        try extract_entry(&reader, entry, relative, dir);
        index += 1;
        if (index % 8 == 0 or index == total) {
            set_progress(@as(f32, @floatFromInt(index)) / @as(f32, @floatFromInt(total)));
        }
    }
    set_progress(1.0);
}

/// Extract one entry under a caller-chosen relative path.
fn extract_entry(reader: *std.Io.File.Reader, entry: std.zip.Iterator.Entry, relative: []const u8, dir: std.Io.Dir) !void {
    const io = reader.io;
    if (relative[relative.len - 1] == '/') {
        try dir.createDirPath(io, relative[0 .. relative.len - 1]);
        return;
    }
    if (std.fs.path.dirname(relative)) |parent| {
        const parent_dir = try dir.createDirPathOpen(io, parent, .{});
        defer parent_dir.close(io);
        const out = try parent_dir.createFile(io, std.fs.path.basename(relative), .{ .truncate = true });
        defer out.close(io);
        var out_buf: [64 * 1024]u8 = undefined;
        var writer = out.writer(io, &out_buf);
        entry.extractTo(reader, &writer.interface) catch |err| switch (err) {
            error.WriteFailed => return writer.err orelse error.WriteFailed,
            else => return err,
        };
        try writer.interface.flush();
        return;
    }
    const out = try dir.createFile(io, relative, .{ .truncate = true });
    defer out.close(io);
    var out_buf: [64 * 1024]u8 = undefined;
    var writer = out.writer(io, &out_buf);
    entry.extractTo(reader, &writer.interface) catch |err| switch (err) {
        error.WriteFailed => return writer.err orelse error.WriteFailed,
        else => return err,
    };
    try writer.interface.flush();
}

/// Create the Start-menu and Desktop shortcuts through WScript.Shell.
///
/// PowerShell is used instead of IShellLink COM: it is one call, works on every
/// supported Windows version and keeps the installer a single small binary.
fn create_shortcut() void {
    const targets = [_]struct { csidl: c_int, name: []const u8, fallback: c_int }{
        // %ProgramData%\Microsoft\Windows\Start Menu\Programs
        .{ .csidl = 0x0017, .name = "\\Zapret-Zen.lnk", .fallback = 0x0002 },
        // %PUBLIC%\Desktop, then the per-user desktop
        .{ .csidl = 0x0019, .name = "\\Zapret-Zen.lnk", .fallback = 0x0010 },
    };
    const exe_utf8 = std.unicode.utf16LeToUtf8Alloc(g_gpa, g_install_dir.items) catch return;
    const exe = std.fmt.allocPrint(g_gpa, "{s}\\Zapret-Zen.exe", .{exe_utf8}) catch return;

    for (targets) |target| {
        var folder: [32768]u16 = undefined;
        _ = win.SHGetFolderPathW(null, target.csidl, null, 0, &folder);
        if (folder[0] == 0) _ = win.SHGetFolderPathW(null, target.fallback, null, 0, &folder);
        if (folder[0] == 0) continue;
        var folder_len: usize = 0;
        while (folder[folder_len] != 0) : (folder_len += 1) {}
        const folder_utf8 = std.unicode.utf16LeToUtf8Alloc(g_gpa, folder[0..folder_len]) catch continue;
        const link = std.fmt.allocPrint(g_gpa, "{s}{s}", .{ folder_utf8, target.name }) catch continue;
        create_link_script(link, exe, exe_utf8);
    }
}

fn create_link_script(link: []const u8, exe: []const u8, workdir: []const u8) void {
    const script = std.fmt.allocPrint(g_gpa,
        \\$ErrorActionPreference='Stop';$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{s}');$s.TargetPath='{s}';$s.WorkingDirectory='{s}';$s.IconLocation='{s},0';$s.Description='Zapret-Zen - обход DPI';$s.Save()
    , .{ link, exe, workdir, exe }) catch return;

    const cmd = std.fmt.allocPrint(g_gpa,
        \\powershell -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -EncodedCommand {s}
    , .{encode_powershell(script)}) catch return;

    var si: win.STARTUPINFOW = .{};
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    var pi: win.PROCESS_INFORMATION = .{};
    const cmd_w = std.unicode.utf8ToUtf16LeAllocZ(g_gpa, cmd) catch return;
    if (win.CreateProcessW(null, cmd_w.ptr, null, null, 0, CREATE_NO_WINDOW, null, null, &si, &pi) != 0) {
        _ = win.WaitForSingleObject(pi.hProcess, 30000);
        _ = win.CloseHandle(pi.hProcess);
        _ = win.CloseHandle(pi.hThread);
    }
}

fn encode_powershell(script: []const u8) []const u8 {
    var utf16 = g_gpa.alloc(u16, script.len) catch return "";
    const len = std.unicode.utf8ToUtf16Le(utf16, script) catch return "";
    const bytes = std.mem.sliceAsBytes(utf16[0..len]);
    const encoder = std.base64.standard.Encoder;
    const out = g_gpa.alloc(u8, encoder.calcSize(bytes.len)) catch return "";
    return encoder.encode(out, bytes);
}

fn register_uninstall() void {
    const exe_utf8 = std.unicode.utf16LeToUtf8Alloc(g_gpa, g_install_dir.items) catch return;
    const key_path = wide("Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\ZapretZen");
    var key: win.HKEY = undefined;
    if (win.RegCreateKeyExW(HKEY_CURRENT_USER, key_path.ptr, 0, null, 0, KEY_WRITE, null, &key, null) != 0) return;
    defer _ = win.RegCloseKey(key);

    const display = std.fmt.allocPrint(g_gpa, "Zapret-Zen {s}", .{opts.version}) catch return;
    const uninstall = std.fmt.allocPrint(g_gpa, "\"{s}\\Zapret-Zen.exe\" --uninstall", .{exe_utf8}) catch return;
    const icon = std.fmt.allocPrint(g_gpa, "{s}\\Zapret-Zen.exe,0", .{exe_utf8}) catch return;

    set_string(key, "DisplayName", display);
    set_string(key, "DisplayVersion", opts.version);
    set_string(key, "Publisher", "Zapret-Zen");
    set_string(key, "DisplayIcon", icon);
    set_string(key, "InstallLocation", exe_utf8);
    set_string(key, "UninstallString", uninstall);
    set_string(key, "QuietUninstallString", uninstall);
    set_dword(key, "NoModify", 1);
    set_dword(key, "NoRepair", 1);
}

fn set_string(key: win.HKEY, name: []const u8, value: []const u8) void {
    const name_z = wide(name);
    const utf16 = g_gpa.alloc(u16, value.len) catch return;
    const len = std.unicode.utf8ToUtf16Le(utf16, value) catch return;
    const bytes = std.mem.sliceAsBytes(utf16[0..len]);
    _ = win.RegSetValueExW(key, name_z.ptr, 0, REG_SZ, @ptrCast(bytes.ptr), @intCast(bytes.len));
}

fn set_dword(key: win.HKEY, name: []const u8, value: u32) void {
    const name_z = wide(name);
    _ = win.RegSetValueExW(key, name_z.ptr, 0, REG_DWORD, @ptrCast(&value), 4);
}

fn launch_app() void {
    const exe_utf8 = std.unicode.utf16LeToUtf8Alloc(g_gpa, g_install_dir.items) catch return;
    const exe = std.fmt.allocPrint(g_gpa, "{s}\\Zapret-Zen.exe", .{exe_utf8}) catch return;
    const exe_w = std.unicode.utf8ToUtf16LeAllocZ(g_gpa, exe) catch return;
    const workdir_w = std.unicode.utf8ToUtf16LeAllocZ(g_gpa, exe_utf8) catch return;
    const open = std.unicode.utf8ToUtf16LeAllocZ(g_gpa, "open") catch return;
    _ = win.ShellExecuteW(g_hwnd, open.ptr, exe_w.ptr, null, workdir_w.ptr, SW_SHOWNORMAL);
}

fn worker(thread: std.Thread) void {
    _ = thread;
    const payload = materialise_payload() catch |err| {
        g_error_text = switch (err) {
            error.PayloadMissing => "Рядом с установщиком нет файла payload.zip (Zapret-Zen-portable.zip). Скачайте установщик заново.",
            else => "Не удалось подготовить файлы для распаковки.",
        };
        g_state = .failed;
        if (g_hwnd) |hwnd| _ = win.PostMessageW(hwnd, WM_FAILED, 0, 0);
        return;
    };
    clear_previous_install();
    extract_all(payload, g_install_utf8) catch |err| {
        g_error_text = switch (err) {
            error.AccessDenied, error.PermissionDenied => "Нет прав на запись в Program Files. Запустите установщик от имени администратора.",
            error.PathAlreadyExists => "Файлы уже существуют и не могут быть заменены. Закройте Zapret-Zen и повторите установку.",
            else => "Распаковка не удалась. Проверьте свободное место и права на папку Program Files.",
        };
        g_state = .failed;
        if (g_hwnd) |hwnd| _ = win.PostMessageW(hwnd, WM_FAILED, 0, 0);
        return;
    };
    create_shortcut();
    register_uninstall();
    g_state = .done;
    if (g_silent) {
        // Silent installs are usually followed by a manual launch; the GUI path
        // honours the checkbox instead.
        if (g_hwnd) |hwnd| _ = win.PostMessageW(hwnd, WM_FINISHED, 0, 0);
        return;
    }
    if (g_hwnd) |hwnd| _ = win.PostMessageW(hwnd, WM_FINISHED, 0, 0);
}

fn start_install() void {
    if (g_state == .working) return;
    g_state = .working;
    set_progress(0.0);
    set_control_text(g_status, "Распаковка файлов…");
    if (g_install_btn) |b| _ = win.EnableWindow(b, 0);
    const thread = std.Thread.spawn(.{}, worker, .{undefined}) catch {
        g_state = .failed;
        g_error_text = "Не удалось запустить установку (не хватает ресурсов).";
        _ = win.PostMessageW(g_hwnd, WM_FAILED, 0, 0);
        return;
    };
    thread.detach();
}

fn finish_ok() void {
    set_control_text(g_status, "Готово. Zapret-Zen установлен, ярлык добавлен на рабочий стол.");
    set_control_text(g_cancel_btn, "Закрыть");
    // The checkbox is pre-ticked: a first-run launch is what users expect after
    // pressing "Установить".
    if (g_launch_box) |b| _ = win.SendMessageW(b, BM_SETCHECK, @intCast(BST_CHECKED), 0);
    if (g_hwnd) |hwnd| _ = win.InvalidateRect(hwnd, null, 0);
}

fn finish_fail() void {
    g_state = .failed;
    set_control_text(g_status, "Установка не завершена.");
    if (g_install_btn) |b| _ = win.EnableWindow(b, 1);
    message_box(g_error_text, 0x10);
}

fn static_text(text: []const u8, x: c_int, y: c_int, w: c_int, h: c_int, id: usize) ?win.HWND {
    const text_z = std.unicode.utf8ToUtf16LeAllocZ(g_gpa, text) catch return null;
    const hwnd = win.CreateWindowExW(0, std.unicode.utf8ToUtf16LeAllocZ(g_gpa, "STATIC") catch return null, text_z.ptr, WS_CHILD | WS_VISIBLE | SS_LEFT, x, y, w, h, g_hwnd, @ptrFromInt(id), null, null);
    if (hwnd) |hw| _ = win.SendMessageW(hw, WM_SETFONT, @intCast(@intFromPtr(g_font_body.?)), 1);
    return hwnd;
}

fn button(text: []const u8, x: c_int, y: c_int, w: c_int, h: c_int, id: usize) ?win.HWND {
    const text_z = std.unicode.utf8ToUtf16LeAllocZ(g_gpa, text) catch return null;
    const hwnd = win.CreateWindowExW(0, std.unicode.utf8ToUtf16LeAllocZ(g_gpa, "BUTTON") catch return null, text_z.ptr, WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON, x, y, w, h, g_hwnd, @ptrFromInt(id), null, null);
    if (hwnd) |hw| _ = win.SendMessageW(hw, WM_SETFONT, @intCast(@intFromPtr(g_font_body.?)), 1);
    return hwnd;
}

fn checkbox(text: []const u8, x: c_int, y: c_int, w: c_int, h: c_int, id: usize) ?win.HWND {
    const text_z = std.unicode.utf8ToUtf16LeAllocZ(g_gpa, text) catch return null;
    const hwnd = win.CreateWindowExW(0, std.unicode.utf8ToUtf16LeAllocZ(g_gpa, "BUTTON") catch return null, text_z.ptr, WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_AUTOCHECKBOX, x, y, w, h, g_hwnd, @ptrFromInt(id), null, null);
    if (hwnd) |hw| _ = win.SendMessageW(hw, WM_SETFONT, @intCast(@intFromPtr(g_font_small.?)), 1);
    return hwnd;
}

fn build_controls() void {
    const seg = "Segoe UI";
    const seg_z = std.unicode.utf8ToUtf16LeAllocZ(g_gpa, seg) catch return;
    g_font_body = win.CreateFontW(-19, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, seg_z.ptr);
    g_font_small = win.CreateFontW(-16, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, seg_z.ptr);
    g_font_title = win.CreateFontW(-30, 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 5, 0, seg_z.ptr);

    g_bg_brush = win.CreateSolidBrush(C_BG);
    g_card_brush = win.CreateSolidBrush(C_CARD);
    g_track_brush = win.CreateSolidBrush(C_TRACK);
    g_accent_brush = win.CreateSolidBrush(C_ACCENT);

    const install_path = std.unicode.utf16LeToUtf8Alloc(g_gpa, g_install_dir.items) catch "";
    const hint = std.fmt.allocPrint(g_gpa, "Программа будет установлена в: {s}", .{install_path}) catch "";
    _ = static_text(hint, 32, 128, 560, 22, ID_PATH);

    _ = static_text("Создать ярлык в меню «Пуск» и запись об удалении", 32, 162, 560, 22, 0);

    g_status = static_text("Нажмите «Установить», чтобы начать.", 32, 216, 560, 22, 0);
    g_launch_box = checkbox("Запустить Zapret-Zen после установки", 32, 268, 400, 24, ID_LAUNCH);
    g_install_btn = button("Установить", 372, 300, 110, 32, ID_INSTALL);
    g_cancel_btn = button("Отмена", 492, 300, 100, 32, ID_CANCEL);
}

fn paint(hwnd: win.HWND) void {
    var ps: win.PAINTSTRUCT = .{};
    const hdc = win.BeginPaint(hwnd, &ps) orelse return;
    defer _ = win.EndPaint(hwnd, &ps);

    var client: win.RECT = .{};
    _ = win.GetClientRect(hwnd, &client);
    _ = win.FillRect(hdc, &client, g_bg_brush);

    // header card
    var header = win.RECT{ .left = 0, .top = 0, .right = client.right, .bottom = 104 };
    _ = win.FillRect(hdc, &header, g_card_brush);

    _ = win.SetBkMode(hdc, TRANSPARENT);
    const old_font = win.SelectObject(hdc, g_font_title);
    _ = win.SetTextColor(hdc, C_TEXT);
    const title = wide("Zapret-Zen");
    var title_rect = win.RECT{ .left = 32, .top = 22, .right = client.right - 32, .bottom = 60 };
    _ = win.DrawTextW(hdc, title.ptr, @intCast(title.len), &title_rect, DT_LEFT | DT_SINGLELINE | DT_NOPREFIX);
    var sub_rect = win.RECT{ .left = 32, .top = 60, .right = client.right - 32, .bottom = 88 };
    const sub_text = std.fmt.allocPrint(g_gpa, "Версия {s} · установка для Windows x64/arm64", .{opts.version}) catch "";
    const sub = wide(sub_text);
    _ = win.SelectObject(hdc, g_font_small);
    _ = win.SetTextColor(hdc, C_MUTED);
    _ = win.DrawTextW(hdc, sub.ptr, @intCast(sub.len), &sub_rect, DT_LEFT | DT_SINGLELINE | DT_NOPREFIX);
    _ = win.SelectObject(hdc, old_font);

    // progress track + fill
    const bar = win.RECT{ .left = 32, .top = 248, .right = client.right - 32, .bottom = 258 };
    _ = win.FillRect(hdc, &bar, g_track_brush);
    if (g_progress > 0.0) {
        const width = @as(f32, @floatFromInt(bar.right - bar.left)) * g_progress;
        var filled = win.RECT{ .left = bar.left, .top = bar.top, .right = bar.left + @as(c_long, @intFromFloat(width)), .bottom = bar.bottom };
        _ = win.FillRect(hdc, &filled, g_accent_brush);
    }
}

fn wnd_proc(hwnd: win.HWND, message: u32, wparam: win.WPARAM, lparam: win.LPARAM) callconv(.winapi) win.LRESULT {
    return switch (message) {
        WM_CREATE => {
            g_hwnd = hwnd;
            build_controls();
            return 0;
        },
        WM_PAINT => {
            paint(hwnd);
            return 0;
        },
        WM_PROGRESS => {
            set_progress(g_progress);
            return 0;
        },
        WM_FINISHED => {
            finish_ok();
            if (g_silent) {
                if (g_launch_box) |b| _ = win.SendMessageW(b, BM_SETCHECK, @intCast(BST_CHECKED), 0);
                _ = win.DestroyWindow(hwnd);
            }
            return 0;
        },
        WM_FAILED => {
            finish_fail();
            if (g_silent) {
                _ = win.DestroyWindow(hwnd);
            }
            return 0;
        },
        WM_COMMAND => {
            const id = wparam & 0xFFFF;
            if (id == ID_INSTALL) {
                start_install();
                return 0;
            }
            if (id == ID_CANCEL) {
                if (g_state == .working) return 0;
                if (g_state == .done) {
                    if (g_launch_box) |b| {
                        if (win.SendMessageW(b, BM_GETCHECK, 0, 0) == BST_CHECKED) launch_app();
                    }
                }
                _ = win.DestroyWindow(hwnd);
                return 0;
            }
            return 0;
        },
        WM_CLOSE => {
            if (g_state == .working) return 0;
            if (g_state == .done) {
                if (g_launch_box) |b| {
                    if (win.SendMessageW(b, BM_GETCHECK, 0, 0) == BST_CHECKED) launch_app();
                }
            }
            _ = win.DestroyWindow(hwnd);
            return 0;
        },
        WM_DESTROY => {
            win.PostQuitMessage(0);
            return 0;
        },
        else => win.DefWindowProcW(hwnd, message, wparam, lparam),
    };
}

fn parse_flags() void {
    const cmd = std.mem.span(win.GetCommandLineW());
    const cmd_utf8 = std.unicode.utf16LeToUtf8Alloc(g_gpa, cmd) catch return;
    var it = std.mem.tokenizeAny(u8, cmd_utf8, " \t\"");
    while (it.next()) |token| {
        if (std.ascii.eqlIgnoreCase(token, "--silent") or std.ascii.eqlIgnoreCase(token, "/S")) g_silent = true;
    }
}

pub fn main() void {
    _ = wWinMain(win.GetModuleHandleW(null).?, null, null, 0);
}

export fn wWinMain(instance: win.HINSTANCE, prev: ?win.HINSTANCE, cmdline: ?[*:0]u16, show: c_int) c_int {
    _ = prev;
    _ = cmdline;
    _ = show;

    var debug_allocator: std.heap.DebugAllocator(.{}) = .init;
    g_gpa = debug_allocator.allocator();
    g_threaded = .init(g_gpa, .{});
    g_io = g_threaded.io();
    g_arena = .init(std.heap.page_allocator);
    defer g_arena.deinit();

    parse_flags();
    compute_paths() catch {
        message_box("Не удалось определить папку установки. Запустите установщик обычным двойным щелчком.", 0x10);
        return 1;
    };

    const class_name = std.unicode.utf8ToUtf16LeAllocZ(g_gpa, "ZapretZenInstaller") catch return 1;
    const title = std.unicode.utf8ToUtf16LeAllocZ(g_gpa, "Установка Zapret-Zen") catch return 1;

    const wc: win.WNDCLASSEXW = .{
        .lpfnWndProc = &wnd_proc,
        .hInstance = instance,
        .hCursor = win.LoadCursorW(null, @ptrFromInt(IDC_ARROW)),
        .lpszClassName = class_name.ptr,
    };
    _ = win.RegisterClassExW(&wc);

    const width: c_int = 640;
    const height: c_int = 400;
    const screen_w = win.GetSystemMetrics(0);
    const screen_h = win.GetSystemMetrics(1);
    const style = WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX;
    g_hwnd = win.CreateWindowExW(0, class_name.ptr, title.ptr, style,
        @divTrunc(screen_w - width, 2), @divTrunc(screen_h - height, 2), width, height,
        null, null, instance, null) orelse return 1;

    if (g_silent) {
        start_install();
        var msg: win.MSG = .{};
        while (win.GetMessageW(&msg, null, 0, 0) > 0) {
            _ = win.TranslateMessage(&msg);
            _ = win.DispatchMessageW(&msg);
        }
        return if (g_state == .done) 0 else 2;
    }

    _ = win.ShowWindow(g_hwnd.?, SW_SHOW);
    _ = win.UpdateWindow(g_hwnd.?);

    var msg: win.MSG = .{};
    while (win.GetMessageW(&msg, null, 0, 0) > 0) {
        _ = win.TranslateMessage(&msg);
        _ = win.DispatchMessageW(&msg);
    }
    return if (g_state == .failed) 2 else 0;
}
