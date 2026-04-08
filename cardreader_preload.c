/*
 * LD_PRELOAD v24 - TRACE ALL fopen calls
 * Log every fopen call that contains "card" or "sys/kernel"
 * to confirm fopen is actually being intercepted.
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <string.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/syscall.h>
#include <sys/stat.h>
#include <sys/mman.h>

static const char *TARGET = "/sys/kernel/recalbox-card-reader";
static const char *FAKE   = "/tmp/fake-card-reader";
static const char *ACTIVE = "/tmp/fake-card-reader/active";

static int (*real_stat64)(const char *, struct stat64 *) = NULL;
static FILE* (*real_fopen)(const char *, const char *) = NULL;
static FILE* (*real_fopen64)(const char *, const char *) = NULL;
static volatile int initialized = 0;
static volatile int fopen_call_count = 0;

__attribute__((constructor))
static void init(void)
{
    real_stat64 = dlsym(RTLD_NEXT, "stat64");
    real_fopen = dlsym(RTLD_NEXT, "fopen");
    real_fopen64 = dlsym(RTLD_NEXT, "fopen64");
    initialized = 1;
}

static void trace(const char *msg)
{
    int len = strlen(msg);
    int fd = syscall(SYS_openat, AT_FDCWD, "/tmp/preload.log",
                    O_WRONLY|O_CREAT|O_APPEND, 0644);
    if (fd >= 0) { syscall(SYS_write, fd, msg, len); syscall(SYS_close, fd); }
}

static int is_nfc_active(void)
{
    char buf[4] = {0};
    int fd = syscall(SYS_openat, AT_FDCWD, ACTIVE, O_RDONLY);
    if (fd < 0) return 0;
    syscall(SYS_read, fd, buf, 3);
    syscall(SYS_close, fd);
    return (buf[0] == '1');
}

static int get_fake_path(const char *path, char *out, int sz)
{
    if (!path) return 0;
    if (strncmp(path, TARGET, 32) != 0) return 0;
    if (path[32] == '\0') { snprintf(out, sz, "%s", FAKE); return 1; }
    if (path[32] == '/') { snprintf(out, sz, "%s%s", FAKE, path + 32); return 1; }
    return 0;
}

static FILE *make_fake_stream(const char *fakepath)
{
    char content[4096] = {0};
    int rfd = syscall(SYS_openat, AT_FDCWD, fakepath, O_RDONLY);
    if (rfd < 0) return NULL;
    ssize_t n = syscall(SYS_read, rfd, content, sizeof(content) - 1);
    syscall(SYS_close, rfd);
    if (n < 0) n = 0;

    int mfd = memfd_create("card-reader", MFD_CLOEXEC);
    if (mfd < 0) return NULL;
    if (n > 0) syscall(SYS_write, mfd, content, n);
    lseek(mfd, 0, SEEK_SET);

    FILE *f = fdopen(mfd, "r");
    if (!f) syscall(SYS_close, mfd);
    return f;
}

/* stat64 */
int stat64(const char *path, struct stat64 *buf)
{
    if (!initialized || !real_stat64)
        return syscall(SYS_newfstatat, AT_FDCWD, path, buf, 0);
    char np[512];
    if (get_fake_path(path, np, sizeof(np)) && is_nfc_active()) {
        int ret = real_stat64(np, buf);
        char msg[512];
        snprintf(msg, sizeof(msg), "[stat64] %s -> %s\n", path, np);
        trace(msg);
        return ret;
    }
    return real_stat64(path, buf);
}

/* fopen - LOG ALL CALLS to see if it's ever called */
FILE *fopen(const char *path, const char *mode)
{
    if (!initialized || !real_fopen) {
        int fd = syscall(SYS_openat, AT_FDCWD, path, O_RDONLY);
        if (fd < 0) return NULL;
        return fdopen(fd, "r");
    }
    
    fopen_call_count++;
    
    /* Log ANY fopen call with "card" or "sys/kernel" or every 1000th call */
    if (path && (strstr(path, "card") || strstr(path, "sys/kernel") || 
                 fopen_call_count <= 5 || (fopen_call_count % 1000) == 0)) {
        char msg[512];
        snprintf(msg, sizeof(msg), "[fopen#%d] path=%s mode=%s\n", 
                fopen_call_count, path, mode ? mode : "null");
        trace(msg);
    }
    
    char np[512];
    if (get_fake_path(path, np, sizeof(np)) && is_nfc_active() && mode && mode[0] == 'r') {
        FILE *f = make_fake_stream(np);
        if (f) {
            char msg[512];
            snprintf(msg, sizeof(msg), "[fopen-REDIR] %s -> %s\n", path, np);
            trace(msg);
            return f;
        }
    }
    
    return real_fopen(path, mode);
}

/* fopen64 */
FILE *fopen64(const char *path, const char *mode)
{
    if (!initialized || !real_fopen64) {
        if (real_fopen) return real_fopen(path, mode);
        int fd = syscall(SYS_openat, AT_FDCWD, path, O_RDONLY);
        if (fd < 0) return NULL;
        return fdopen(fd, "r");
    }
    
    /* Log card-reader calls */
    if (path && (strstr(path, "card") || strstr(path, "sys/kernel"))) {
        char msg[512];
        snprintf(msg, sizeof(msg), "[fopen64] path=%s mode=%s\n", path, mode ? mode : "null");
        trace(msg);
    }
    
    char np[512];
    if (get_fake_path(path, np, sizeof(np)) && is_nfc_active() && mode && mode[0] == 'r') {
        FILE *f = make_fake_stream(np);
        if (f) {
            char msg[512];
            snprintf(msg, sizeof(msg), "[fopen64-REDIR] %s -> %s\n", path, np);
            trace(msg);
            return f;
        }
    }
    
    return real_fopen64(path, mode);
}
