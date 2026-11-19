import getpass
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# Configure console encoding to avoid errors on Windows terminals
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# Automatically locate and change working directory to Project Root
CURRENT_FILE = Path(__file__).resolve()
if (CURRENT_FILE.parent / "app.py").exists():
    PROJECT_ROOT = CURRENT_FILE.parent
elif (CURRENT_FILE.parent / ".git").exists():
    PROJECT_ROOT = CURRENT_FILE.parent
elif (CURRENT_FILE.parent.parent / "app.py").exists():
    PROJECT_ROOT = CURRENT_FILE.parent.parent
elif (CURRENT_FILE.parent.parent / ".git").exists():
    PROJECT_ROOT = CURRENT_FILE.parent.parent
else:
    PROJECT_ROOT = CURRENT_FILE.parent

os.chdir(PROJECT_ROOT)

DEFAULT_ORIGIN_URL = "https://github.com/teerayut444/NOVA-P.git"
DEFAULT_GIT_USER = "teerayut444"
DEFAULT_GIT_EMAIL = "teerayut444@users.noreply.github.com"
PLACEHOLDER_IDENTITIES = {
    "",
    "your name",
    "your.email@example.com",
    "you@example.com",
    "email@example.com",
    "none",
}


def _configure_git_path(candidate):
    """Ensure Git and its helper directories (needed by GCM) are present in PATH."""
    cand_dir = os.path.dirname(os.path.abspath(candidate))
    if os.path.basename(cand_dir).lower() in ("cmd", "bin"):
        git_root = os.path.dirname(cand_dir)
    else:
        git_root = cand_dir

    dirs_to_add = [
        os.path.join(git_root, "cmd"),
        os.path.join(git_root, "bin"),
        os.path.join(git_root, "mingw64", "bin"),
        os.path.join(git_root, "usr", "bin"),
    ]
    current_path = os.environ.get("PATH", "")
    existing_norm = {os.path.normcase(p) for p in current_path.split(os.pathsep) if p}
    for d in reversed(dirs_to_add):
        if os.path.isdir(d) and os.path.normcase(d) not in existing_norm:
            current_path = d + os.pathsep + current_path if current_path else d
            existing_norm.add(os.path.normcase(d))
    os.environ["PATH"] = current_path


def find_git_executable():
    """Dynamically locate git executable lazily and configure necessary PATH directories."""
    fast_candidates = [
        shutil.which("git"),
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files\Git\bin\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\bin\git.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin\git.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Git\cmd\git.exe"),
        os.path.expandvars(r"%PROGRAMDATA%\chocolatey\bin\git.exe"),
    ]

    for candidate in fast_candidates:
        if candidate and os.path.isfile(candidate):
            _configure_git_path(candidate)
            return candidate

    # Fallback: search GitHub Desktop installation only if standard paths were not found
    gh_desktop = os.path.expandvars(r"%LOCALAPPDATA%\GitHubDesktop")
    if os.path.isdir(gh_desktop):
        for root, _, files in os.walk(gh_desktop):
            if "git.exe" in files:
                candidate = os.path.join(root, "git.exe")
                _configure_git_path(candidate)
                return candidate

    return None


GIT_PATH = find_git_executable()


def run_git_command(args, check=True, strip_output=True, input_text=None, extra_env=None):
    """Run a non-interactive git command and return its stdout, or None on non-fatal failure."""
    global GIT_PATH
    if not GIT_PATH:
        GIT_PATH = find_git_executable()
        if not GIT_PATH:
            print("[-] ไม่พบโปรแกรม Git ในเครื่อง กรุณาติดตั้ง Git for Windows จาก https://git-scm.com/download/win")
            if check:
                sys.exit(1)
            return None

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    command = [GIT_PATH] + args
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            input=input_text,
            check=False,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        if result.returncode != 0:
            if check:
                err_msg = result.stderr.strip() if result.stderr else (result.stdout.strip() if result.stdout else "ไม่มีรายละเอียด")
                print(f"[-] เกิดข้อผิดพลาดขณะรันคำสั่ง git {' '.join(args)}")
                print(f"รายละเอียดข้อผิดพลาด:\n{err_msg}")
                sys.exit(1)
            return None
        return result.stdout.strip() if strip_output else result.stdout.rstrip("\r\n")
    except FileNotFoundError:
        print(f"[-] ไม่พบโปรแกรม Git ที่พาธ: {GIT_PATH}")
        if check:
            sys.exit(1)
        return None


def run_git_interactive(args, extra_env=None):
    """Run interactive git commands (push, fetch, pull) with terminal I/O."""
    global GIT_PATH
    if not GIT_PATH:
        GIT_PATH = find_git_executable()
        if not GIT_PATH:
            print("[-] ไม่พบโปรแกรม Git ในเครื่อง")
            return False

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    command = [GIT_PATH] + args
    result = subprocess.run(command, env=env)
    return result.returncode == 0


def mask_url_credentials(text):
    """Mask any embedded credentials inside HTTPS URLs before printing."""
    return re.sub(r"https://[^@\s]+@", "https://***@", text)


def ensure_git_identity_and_config():
    """Ensure Git has valid user.name, user.email, UTF-8 paths, and reliable auth mode."""
    name = (run_git_command(["config", "user.name"], check=False) or "").strip()
    email = (run_git_command(["config", "user.email"], check=False) or "").strip()

    if name.lower() in PLACEHOLDER_IDENTITIES:
        run_git_command(["config", "--local", "user.name", DEFAULT_GIT_USER], check=False)
        print(f"[Git Config] ตั้งค่า local user.name = {DEFAULT_GIT_USER}")

    if email.lower() in PLACEHOLDER_IDENTITIES:
        run_git_command(["config", "--local", "user.email", DEFAULT_GIT_EMAIL], check=False)
        print(f"[Git Config] ตั้งค่า local user.email = {DEFAULT_GIT_EMAIL}")

    # Prevent octal escaping of UTF-8 Thai file paths
    run_git_command(["config", "--local", "core.quotepath", "false"], check=False)

    # Use devicecode mode by default to prevent "127.0.0.1 refused to connect"
    auth_mode = run_git_command(["config", "credential.gitHubAuthModes"], check=False)
    if not auth_mode:
        run_git_command(["config", "--local", "credential.gitHubAuthModes", "devicecode"], check=False)
        print("[Git Config] กำหนดโหมดล็อกอินเป็น Device Code (ป้องกันปัญหา 127.0.0.1)")


def get_current_branch():
    """Return the active branch name, or None if HEAD is detached."""
    branch = run_git_command(["symbolic-ref", "--short", "HEAD"], check=False)
    return branch if branch else None


def get_origin_url():
    """Return the configured 'origin' URL, or None if no 'origin' remote exists."""
    return run_git_command(["remote", "get-url", "origin"], check=False)


def _normalize_repo_identifier(url):
    """Normalize HTTPS/SSH GitHub remote URLs into a comparable lowercase identifier."""
    if not url:
        return ""
    cleaned = re.sub(r"^(https?://)[^@]+@", r"\1", url.strip())
    ssh_match = re.match(r"^(?:ssh://)?git@github\.com[:/](.+?)(?:\.git)?/?$", cleaned, re.IGNORECASE)
    if ssh_match:
        return f"github.com/{ssh_match.group(1).lower()}"
    parsed = urlparse(cleaned)
    if parsed.hostname:
        path = parsed.path.strip("/")
        if path.lower().endswith(".git"):
            path = path[:-4]
        return f"{parsed.hostname.lower()}/{path.lower()}"
    cleaned = cleaned.rstrip("/")
    if cleaned.lower().endswith(".git"):
        cleaned = cleaned[:-4]
    return cleaned.lower()


def ensure_origin_remote(branch=None):
    """Ensure 'origin' points to DEFAULT_ORIGIN_URL without embedded credentials."""
    origin_url = get_origin_url()
    if not origin_url:
        print(f"\n[Git] กำหนดค่า GitHub Remote ('origin') -> {DEFAULT_ORIGIN_URL}")
        run_git_command(["remote", "add", "origin", DEFAULT_ORIGIN_URL])
        return DEFAULT_ORIGIN_URL

    clean_url = re.sub(r"https://[^@]+@", "https://", origin_url)
    if _normalize_repo_identifier(clean_url) != _normalize_repo_identifier(DEFAULT_ORIGIN_URL):
        print(
            "\n[Git] อัปเดต GitHub Remote ('origin') ให้เชื่อมไปยังโปรเจกต์นี้:\n"
            f"      เดิม : {mask_url_credentials(origin_url)}\n"
            f"      ใหม่ : {DEFAULT_ORIGIN_URL}"
        )
        run_git_command(["remote", "set-url", "origin", DEFAULT_ORIGIN_URL])
        if branch:
            run_git_command(["update-ref", "-d", f"refs/remotes/origin/{branch}"], check=False)
        return DEFAULT_ORIGIN_URL

    if clean_url != origin_url:
        run_git_command(["remote", "set-url", "origin", clean_url], check=False)
        print(f"[Git] ตรวจพบ GitHub Remote (ล้าง Token ฝังใน URL แล้ว): {clean_url}")
        return clean_url

    print(f"[Git] ตรวจพบ GitHub Remote: {clean_url}")
    return clean_url


def _prompt_pat_secret():
    """Read Personal Access Token without echoing characters to the terminal when possible."""
    prompt = "วาง Personal Access Token ของคุณที่นี่ (หรือกด Enter เพื่อยกเลิก): "
    try:
        return getpass.getpass(prompt).strip()
    except Exception:
        return input(prompt).strip()


def _store_pat_in_credential_manager(origin_url, token):
    """Store PAT in Git's configured credential helper (e.g., Windows Credential Manager)."""
    parsed = urlparse(origin_url)
    host = parsed.hostname
    protocol = parsed.scheme or "https"
    if not host:
        return False

    cred_clear = f"protocol={protocol}\nhost={host}\n\n"
    cred_approve = f"protocol={protocol}\nhost={host}\nusername=oauth2\npassword={token}\n\n"
    non_interactive = {"GCM_INTERACTIVE": "never", "GIT_TERMINAL_PROMPT": "0"}

    # Clear stale credential for this host first so the new PAT takes effect
    run_git_command(["credential", "reject"], check=False, input_text=cred_clear, extra_env=non_interactive)
    approved = run_git_command(["credential", "approve"], check=False, input_text=cred_approve, extra_env=non_interactive)
    return approved is not None


def _push_with_temporary_askpass(branch, token, force_push=False):
    """Push using an ephemeral GIT_ASKPASS script without writing plaintext secrets to .git/config."""
    py_file = None
    cmd_file = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as pf:
            pf.write(
                "import os, sys\n"
                "prompt = ' '.join(sys.argv[1:]).lower()\n"
                "print('oauth2' if 'username' in prompt else os.environ.get('NOVA_GIT_ASKPASS_TOKEN', ''))\n"
            )
            py_file = pf.name

        with tempfile.NamedTemporaryFile("w", suffix=".cmd", delete=False, encoding="utf-8") as cf:
            cf.write(f'@echo off\r\n"{sys.executable}" "{py_file}" %*\r\n')
            cmd_file = cf.name

        askpass_env = {
            "GIT_ASKPASS": cmd_file,
            "NOVA_GIT_ASKPASS_TOKEN": token,
            "GCM_INTERACTIVE": "never",
            "GIT_TERMINAL_PROMPT": "0",
        }
        push_args = ["-c", "credential.helper=", "push"]
        if force_push:
            push_args.append("--force-with-lease")
        push_args.extend(["-u", "origin", branch])
        return run_git_interactive(push_args, extra_env=askpass_env)
    finally:
        for temp_path in (cmd_file, py_file):
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


def setup_pat_token():
    """Prompt user for a GitHub PAT and configure it securely (never plaintext in .git/config)."""
    origin_url = get_origin_url() or DEFAULT_ORIGIN_URL
    clean_url = re.sub(r"https://[^@]+@", "https://", origin_url)

    if not clean_url.startswith("https://"):
        print(f"[-] Remote 'origin' ไม่ใช่ HTTPS ({origin_url}) จึงไม่สามารถใช้ PAT กับ URL นี้ได้")
        return None, None

    # Remove any legacy embedded token in .git/config if previously saved
    if clean_url != origin_url:
        run_git_command(["remote", "set-url", "origin", clean_url], check=False)

    print("\n" + "=" * 65)
    print("   ตั้งค่าเชื่อมต่อด้วย GitHub Personal Access Token (PAT)")
    print("=" * 65)
    print("วิธีสร้าง Token ใน 1 นาที:")
    print("  1. เปิดเว็บ: https://github.com/settings/tokens")
    print("  2. กด 'Generate new token (classic)'")
    print("  3. ติ๊กถูกช่อง [x] repo และ [x] workflow (จำเป็นเมื่อแก้ไข .github/workflows/)")
    print("  4. กด Generate token แล้วคัดลอกรหัส (ขึ้นต้นด้วย ghp_...)")
    print("=" * 65)

    token = _prompt_pat_secret()
    if not token:
        return None, None

    if _store_pat_in_credential_manager(clean_url, token):
        print("[Git] บันทึก Token ลงใน Credential Manager ของเครื่องเรียบร้อยแล้ว!")
        return "credential_manager", None

    print("[Git] Credential Manager ไม่พร้อมใช้งาน จะใช้ Token ชั่วคราวสำหรับการ Push รอบนี้")
    return "askpass", token


def _is_scraper_exe(rel_path):
    """Return True if path is a Scraper_Monthly_Parallel executable."""
    name = os.path.basename(rel_path).lower()
    return "scraper_monthly_parallel" in name and name.endswith(".exe")


def _is_tracked_in_head(rel_path):
    """Return True if rel_path exists in the current HEAD commit."""
    return run_git_command(["cat-file", "-e", f"HEAD:{rel_path}"], check=False) is not None


def _unstage_path(rel_path, has_head=True):
    """Unstage a path safely without deleting already-tracked files from Git."""
    if has_head and _is_tracked_in_head(rel_path):
        run_git_command(["reset", "HEAD", "--", rel_path], check=False)
        return "reset"
    run_git_command(["rm", "--cached", "-f", "--", rel_path], check=False)
    return "removed_from_index"


def _untrack_staged_or_tracked_scraper_exe():
    """Ensure any Scraper_Monthly_Parallel*.exe in the Git index is untracked."""
    tracked = run_git_command(["ls-files"], check=False)
    if not tracked:
        return
    for rel_path in tracked.splitlines():
        rel_path = rel_path.strip().strip('"')
        if rel_path and _is_scraper_exe(rel_path):
            run_git_command(["rm", "--cached", "-f", "--", rel_path], check=False)
            print(f"[Exclude] นำ '{rel_path}' ออกจาก Git index (ไฟล์ในเครื่องยังอยู่)")


def ensure_large_files_excluded(max_size_mb=95, has_head=True):
    """Ensure Scraper_Monthly_Parallel.exe and files exceeding max_size_mb are never committed."""
    _untrack_staged_or_tracked_scraper_exe()

    staged = run_git_command(["diff", "--cached", "--name-only"], check=False)
    if not staged:
        return

    skipped_unignored = []
    for rel_path in staged.splitlines():
        rel_path = rel_path.strip().strip('"')
        if not rel_path:
            continue

        if _is_scraper_exe(rel_path):
            _unstage_path(rel_path, has_head=has_head)
            print(f"[Exclude] ข้ามการอัปโหลด '{rel_path}' (ไฟล์ Scraper exe ขนาดใหญ่ ไม่ต้องนำขึ้น GitHub)")
            continue

        full_path = PROJECT_ROOT / rel_path
        if full_path.is_file():
            try:
                size_mb = full_path.stat().st_size / (1024 * 1024)
                if size_mb > max_size_mb:
                    action = _unstage_path(rel_path, has_head=has_head)
                    print(
                        f"[Exclude] ข้ามไฟล์ขนาดใหญ่ '{rel_path}' ({size_mb:.1f} MB > {max_size_mb} MB) "
                        "ไม่ให้อัปโหลดขึ้น GitHub"
                    )
                    if action == "removed_from_index":
                        skipped_unignored.append(rel_path)
            except OSError:
                pass

    if skipped_unignored:
        print("[Tip] แนะนำให้เพิ่มไฟล์ขนาดใหญ่ด้านบนลงใน .gitignore เพื่อไม่ให้ค้างในสถานะรออัปโหลดรอบถัดไป")


def _find_oversized_unpushed_files(branch, max_size_mb=95):
    """Return list of oversized (>max_size_mb) or Scraper exe paths in unpushed commits."""
    flagged = set()
    rev_range = f"origin/{branch}..HEAD"

    changed_paths = run_git_command(["log", rev_range, "--name-only", "--pretty=format:"], check=False)
    if changed_paths:
        for rel_path in changed_paths.splitlines():
            rel_path = rel_path.strip().strip('"')
            if rel_path and _is_scraper_exe(rel_path):
                flagged.add(rel_path)

    rev_objects = run_git_command(["rev-list", "--objects", rev_range], check=False)
    if rev_objects:
        batch_info = run_git_command(
            ["cat-file", "--batch-check=%(objecttype) %(objectsize) %(rest)"],
            check=False,
            input_text=rev_objects + "\n",
        )
        max_bytes = max_size_mb * 1024 * 1024
        if batch_info:
            for line in batch_info.splitlines():
                parts = line.split(" ", 2)
                if len(parts) == 3 and parts[0] == "blob":
                    try:
                        if int(parts[1]) > max_bytes:
                            flagged.add(parts[2])
                    except ValueError:
                        pass

    return sorted(flagged)


def clean_unpushed_large_commits(branch, max_size_mb=95):
    """Detect and soft-reset unpushed commits that accidentally included oversized files."""
    try:
        if not get_origin_url():
            return
        if run_git_command(["rev-parse", "--verify", f"origin/{branch}"], check=False) is None:
            return
        if not run_git_command(["merge-base", f"origin/{branch}", "HEAD"], check=False):
            return

        flagged = _find_oversized_unpushed_files(branch, max_size_mb=max_size_mb)
        if not flagged:
            return

        print(f"\n[Guard] ตรวจพบไฟล์ต้องห้าม/ขนาดเกิน {max_size_mb} MB ใน Commit ที่ยังไม่ได้ Push:")
        for p in flagged:
            print(f"  - {p}")

        reset_target = run_git_command(["merge-base", f"origin/{branch}", "HEAD"], check=False) or f"origin/{branch}"
        print(f"[Guard] กำลังปลด Commit ชั่วคราว (git reset --soft {reset_target[:7]}) เพื่อคัดไฟล์เหล่านี้ออก...")
        run_git_command(["reset", "--soft", reset_target], check=False)

        has_head = run_git_command(["rev-parse", "--verify", "HEAD"], check=False) is not None
        for p in flagged:
            _unstage_path(p, has_head=has_head)
        ensure_large_files_excluded(max_size_mb=max_size_mb, has_head=has_head)
        print("[Guard] ปลดไฟล์ออกเรียบร้อยแล้ว (ไฟล์ในเครื่องยังอยู่ครบถ้วน)")
    except Exception as exc:
        print(f"[Warning] ตรวจสอบไฟล์ขนาดใหญ่ใน unpushed commits ไม่สมบูรณ์: {exc}")


def _get_ahead_behind(branch):
    """Return (behind, ahead) commit counts compared to origin/<branch>, or None if unknown."""
    if run_git_command(["rev-parse", "--verify", f"origin/{branch}"], check=False) is None:
        return None
    counts = run_git_command(["rev-list", "--left-right", "--count", f"origin/{branch}...HEAD"], check=False)
    if not counts:
        return None
    parts = counts.split()
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _has_workflow_changes(branch):
    """Return True if staged changes or unpushed commits touch .github/workflows/."""
    staged = run_git_command(["diff", "--cached", "--name-only"], check=False) or ""
    for line in staged.splitlines():
        if line.strip().strip('"').startswith(".github/workflows/"):
            return True

    if run_git_command(["rev-parse", "--verify", f"origin/{branch}"], check=False) is not None:
        unpushed = run_git_command(["log", f"origin/{branch}..HEAD", "--name-only", "--pretty=format:"], check=False) or ""
        for line in unpushed.splitlines():
            if line.strip().strip('"').startswith(".github/workflows/"):
                return True
    return False


def _is_rebase_in_progress():
    """Return True if Git is currently paused mid-rebase."""
    git_dir = PROJECT_ROOT / ".git"
    return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


def _run_pull_rebase(branch):
    """Safely run git pull --rebase --autostash and provide clear guidance if it fails."""
    print(f"\n[Git] กำลังดึงและ Rebase ข้อมูล (git pull --rebase --autostash origin {branch})...")
    rebase_ok = run_git_interactive(["pull", "--rebase", "--autostash", "origin", branch])
    if rebase_ok:
        return True

    print("\n[-] ไม่สามารถ Rebase ข้อมูลได้")
    if _is_rebase_in_progress():
        print("[!] ตรวจพบ Conflict ระหว่างการ Rebase (Git หยุดรอการแก้ไขอยู่ในสถานะ REBASE)")
        print("    วิธีแก้ไข:")
        print("      1. เปิดไฟล์ที่มี Conflict แล้วแก้ไขให้เรียบร้อย")
        print("      2. รัน: git add .  แล้วตามด้วย  git rebase --continue")
        print("      3. หรือหากต้องการยกเลิกการ Rebase กลับสภาพเดิม รัน: git rebase --abort")
    else:
        print("[!] กรุณาตรวจสอบ error ด้านบน (เช่น ปัญหาการเชื่อมต่อ, สิทธิ์การเข้าถึง หรือไฟล์ค้างในเครื่อง)")
    return False


def _offer_pull_rebase_only(branch, behind):
    """Offer pulling remote commits via rebase when local has nothing to push."""
    print(f"[Info] ไม่มีข้อมูลใหม่สำหรับ Push แต่ GitHub มี {behind} commit ใหม่กว่าเครื่อง")
    ans = input("ต้องการดึงข้อมูลล่าสุดจาก GitHub (git pull --rebase) เลยไหม? (Y/n): ").strip().lower()
    if ans in ("", "y", "yes"):
        if _run_pull_rebase(branch):
            print("[Success] อัปเดตโค้ดในเครื่องให้ตรงกับ GitHub เรียบร้อยแล้ว!")
            return
        sys.exit(1)
    print("[Info] ข้ามการดึงข้อมูลจาก GitHub")


def _has_unrelated_histories(branch):
    """Return True if HEAD and origin/<branch> both exist but share no common ancestor."""
    has_head = run_git_command(["rev-parse", "--verify", "HEAD"], check=False) is not None
    has_remote = run_git_command(["rev-parse", "--verify", f"origin/{branch}"], check=False) is not None
    if not (has_head and has_remote):
        return False
    return run_git_command(["merge-base", f"origin/{branch}", "HEAD"], check=False) is None


def _resolve_unrelated_histories(branch):
    """Handle unrelated commit histories when switching remote to a newly created repo."""
    print("\n" + "!" * 65)
    print(f"[Warning] ประวัติ Commit ในเครื่องไม่เชื่อมโยงกับ origin/{branch} (Unrelated Histories)")
    print("สาเหตุ: โปรเจกต์นี้เพิ่งเปลี่ยน Remote ไปยัง Repository ใหม่ หรือ GitHub มี Commit เริ่มต้นแยกไว้")
    print("!" * 65)
    print("กรุณาเลือกวิธีดำเนินการ:")
    print(f"  1. เชื่อมฐานประวัติต่อจาก origin/{branch} (git reset origin/{branch}) โดยเก็บไฟล์ในเครื่องไว้ทั้งหมด (แนะนำ)")
    print("  2. คงประวัติในเครื่องไว้ แล้วบังคับเขียนทับ GitHub (git push --force-with-lease)")
    print("  3. ยกเลิก")

    choice = input("กรุณาเลือก (1/2/3): ").strip()
    if choice == "1":
        print(f"\n[Git] กำลังปรับฐาน Commit ไปที่ origin/{branch} (ไม่กระทบไฟล์ในเครื่อง)...")
        run_git_command(["reset", f"origin/{branch}"])
        run_git_command(["branch", f"--set-upstream-to=origin/{branch}", branch], check=False)
        print(f"[Git] เชื่อมฐานประวัติกับ origin/{branch} เรียบร้อยแล้ว!")
        return True, False
    if choice == "2":
        print("[Git] เลือกใช้โหมดบังคับเขียนทับประวัติบน GitHub (--force-with-lease)")
        return True, True

    print("[Info] ยกเลิกการดำเนินการ")
    return False, False


def main():
    print("=" * 65)
    print("   ระบบอัปโหลดไฟล์ขึ้น GitHub สำหรับ NOVA-P Web Dashboard")
    print("=" * 65)
    print(f"[Path] โฟลเดอร์โปรเจกต์: {PROJECT_ROOT}")

    if not GIT_PATH:
        print("[-] ไม่พบโปรแกรม Git ในเครื่อง กรุณาติดตั้ง Git for Windows ก่อนใช้งาน")
        sys.exit(1)
    print(f"[Git] ตรวจพบ Git: {GIT_PATH}")

    # 1. Initialize git if not already present
    is_new_repo = False
    if not (PROJECT_ROOT / ".git").exists():
        print("[Git] ไม่พบโฟลเดอร์ .git กำลังเริ่มต้นระบบ Git Local...")
        run_git_command(["init"])
        run_git_command(["branch", "-M", "main"])
        is_new_repo = True

    if _is_rebase_in_progress():
        print("\n[!] พบสถานะ Rebase ค้างอยู่จากรอบก่อน กรุณาแก้ Conflict ให้เสร็จ (git rebase --continue)")
        print("    หรือยกเลิกก่อน (git rebase --abort) แล้วค่อยรันสคริปต์นี้อีกครั้ง")
        sys.exit(1)

    # 2. Ensure identity & auth config
    ensure_git_identity_and_config()

    # 3. Check active branch & remote origin
    branch = get_current_branch()
    if not branch:
        print("[-] ตรวจพบสถานะ Detached HEAD (ไม่ได้อยู่บน Branch ใด) กรุณา checkout branch ก่อนใช้งาน (เช่น git checkout main)")
        sys.exit(1)
    print(f"[Git] Branch ปัจจุบัน: {branch}")

    ensure_origin_remote(branch=branch)

    # 4. Sync remote refs before inspecting commits/status
    has_head = run_git_command(["rev-parse", "--verify", "HEAD"], check=False) is not None

    if is_new_repo or not has_head:
        print(f"\n[Git] กำลังเชื่อมต่อประวัติ Commit จาก GitHub (git fetch origin {branch})...")
        if run_git_interactive(["fetch", "origin", branch]):
            print("[Git] ดึงประวัติจาก Remote สำเร็จ กำลังปรับฐานข้อมูลให้ตรงกับ GitHub...")
            run_git_command(["reset", f"origin/{branch}"], check=False)
            run_git_command(["branch", f"--set-upstream-to=origin/{branch}", branch], check=False)
            has_head = run_git_command(["rev-parse", "--verify", "HEAD"], check=False) is not None
            print("[Git] ปรับฐานข้อมูลประวัติ Commit เรียบร้อยแล้ว")
        else:
            print("[Git] ข้ามการดึงประวัติ Remote และสร้าง Commit แรกในเครื่อง")
    else:
        print(f"\n[Git] กำลังตรวจสอบสถานะล่าสุดจาก GitHub (git fetch origin {branch})...")
        if not run_git_interactive(["fetch", "origin", branch]):
            print("[Warning] ไม่สามารถดึงสถานะล่าสุดจาก GitHub ได้ (อาจยังไม่ได้ล็อกอิน หรือออฟไลน์) — จะตรวจจากข้อมูลในเครื่องแทน")

    use_force_push = False
    if _has_unrelated_histories(branch):
        resolved_ok, use_force_push = _resolve_unrelated_histories(branch)
        if not resolved_ok:
            sys.exit(0)

    # 4.1 Guard against unpushed commits with large files
    clean_unpushed_large_commits(branch)

    # 4.2 Ensure any Scraper_Monthly_Parallel*.exe is untracked
    _untrack_staged_or_tracked_scraper_exe()

    # 5. Check working tree and ahead/behind state
    print("\n[Check] ตรวจสอบการเปลี่ยนแปลงไฟล์...")
    status = run_git_command(["status", "--porcelain"], strip_output=False)
    ahead_behind = _get_ahead_behind(branch)
    behind, ahead = ahead_behind if ahead_behind else (0, 0)

    need_commit = bool(status and status.strip())
    if need_commit:
        print("[Modified] ไฟล์ที่มีการเปลี่ยนแปลง / เพิ่มใหม่:")
        for line in status.splitlines():
            if line:
                print(f"  {line}")
    else:
        if ahead > 0 and behind > 0:
            print(f"[Info] มี Commit ในเครื่องที่ยังไม่ได้ Push {ahead} รายการ และ GitHub มี Commit ใหม่กว่า {behind} รายการ")
        elif ahead > 0:
            print(f"[Info] มี Commit ในเครื่องที่ยังไม่ได้ Push ไปยัง GitHub ({ahead} รายการ)")
        elif behind > 0:
            _offer_pull_rebase_only(branch, behind)
            return
        else:
            print("[Success] ไม่มีไฟล์ที่มีการเปลี่ยนแปลง และโค้ดตรงกับ GitHub เรียบร้อยแล้ว")
            return

    # 6. Stage and commit if changes exist
    if need_commit:
        print("\n[Git] กำลังสเตจไฟล์ (git add .)...")
        run_git_command(["add", "."])

        ensure_large_files_excluded(has_head=has_head)

        staged_files = run_git_command(["diff", "--cached", "--name-only"], check=False)
        if staged_files and staged_files.strip():
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            commit_msg = f"Auto-update: {timestamp}"
            print(f"[Git] กำลังบันทึกประวัติการแก้ไข (git commit -m \"{commit_msg}\")...")
            commit_out = run_git_command(["commit", "-m", commit_msg])
            if commit_out:
                print(commit_out)
            has_head = True
        else:
            print("[Info] ไม่มีไฟล์ที่ต้อง Commit เพิ่มเติมหลังคัดกรองไฟล์ขนาดใหญ่")
            ahead_behind = _get_ahead_behind(branch)
            behind, ahead = ahead_behind if ahead_behind else (0, 0)
            if ahead == 0 and has_head and run_git_command(["rev-parse", "--verify", f"origin/{branch}"], check=False) is not None:
                if behind > 0:
                    _offer_pull_rebase_only(branch, behind)
                    return
                print("[Success] ข้อมูลทั้งหมดเป็นปัจจุบันแล้ว ไม่จำเป็นต้อง Push")
                return

    # Recompute ahead/behind after commit
    ahead_behind = _get_ahead_behind(branch)
    behind, ahead = ahead_behind if ahead_behind else (0, 0)

    # 6.5 If remote is ahead, offer pull --rebase before pushing to avoid guaranteed rejection
    if behind > 0 and not use_force_push:
        print(f"\n[Warning] GitHub มี {behind} commit ใหม่กว่าในเครื่อง ต้อง Rebase รวมประวัติก่อนจึงจะ Push ได้")
        ans = input("ต้องการดึงข้อมูลล่าสุดมา Rebase (git pull --rebase) ก่อน Push เลยไหม? (Y/n): ").strip().lower()
        if ans in ("", "y", "yes"):
            if not _run_pull_rebase(branch):
                sys.exit(1)

    # 7. Push to GitHub
    push_args = (
        ["push", "--force-with-lease", "-u", "origin", branch]
        if use_force_push
        else ["push", "-u", "origin", branch]
    )
    print("\n" + "=" * 65)
    print(f"   กำลังส่งข้อมูลขึ้น GitHub (git {' '.join(push_args)})...")
    print("=" * 65)
    print("[คำแนะนำการยืนยันตัวตน Device Code]:")
    print("  1. หากระบบแสดงรหัสโค้ด (เช่น ABCD-1234) และลิงก์ https://github.com/login/device")
    print("  2. ให้เปิดเบราว์เซอร์ไปที่ https://github.com/login/device")
    print("  3. กรอกรหัสโค้ดที่แสดง แล้วกด 'Authorize' ในเบราว์เซอร์")
    if _has_workflow_changes(branch):
        print("  [!] หมายเหตุ: รอบนี้มีการแก้ไฟล์ใน .github/workflows/ ต้องใช้สิทธิ์ 'workflow' scope ด้วย")
    print("=" * 65 + "\n")

    if run_git_interactive(push_args):
        print("\n" + "=" * 65)
        print("[Success] อัปโหลดไฟล์และอัปเดตข้อมูลขึ้น GitHub สำเร็จเรียบร้อยแล้ว!")
        print("=" * 65)
        return

    # 8. Recovery options if push failed
    print("\n[-] การ Push ครั้งแรกไม่สำเร็จ")
    print("คุณต้องการดำเนินการอย่างไรต่อ?")
    print("  1. ลองดึงข้อมูลล่าสุด (git pull --rebase) แล้ว Push ใหม่อีกครั้ง")
    print("  2. ใส่ GitHub Personal Access Token (PAT) (แนะนำ หากติดปัญหาล็อกอิน / workflow scope)")
    print("  3. ยกเลิก")

    choice = input("กรุณาเลือก (1/2/3): ").strip()
    if choice == "1":
        if _run_pull_rebase(branch):
            if run_git_interactive(["push", "-u", "origin", branch]):
                print("\n[Success] Rebase และ Push ขึ้น GitHub สำเร็จเรียบร้อยแล้ว!")
                return
    elif choice == "2":
        mode, token = setup_pat_token()
        if mode == "credential_manager":
            print("\n[Git] กำลังลอง Push ด้วย Token...")
            if run_git_interactive(push_args):
                print("\n[Success] Push ขึ้น GitHub ด้วย Token สำเร็จเรียบร้อยแล้ว!")
                return
        elif mode == "askpass" and token:
            print("\n[Git] กำลังลอง Push ด้วย Token ชั่วคราว...")
            if _push_with_temporary_askpass(branch, token, force_push=use_force_push):
                print("\n[Success] Push ขึ้น GitHub ด้วย Token สำเร็จเรียบร้อยแล้ว!")
                return

    print("\n[-] ไม่สามารถ Push ข้อมูลขึ้น GitHub ได้ กรุณาตรวจสอบสิทธิ์การเข้าถึง (repo + workflow) หรือสถานะ Conflict")
    sys.exit(1)


if __name__ == "__main__":
    main()
