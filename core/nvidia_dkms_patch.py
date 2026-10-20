"""
Compatibility patches for NVIDIA DKMS kernel module sources.

Applied to /usr/src/nvidia-*/ before DKMS rebuilds during kernel install.
These patches are backward-compatible — guarded with #ifndef so they are
safe to apply on older kernels where the old symbols still exist.
"""

# Fixes VMA locking API change introduced in Linux 7.x:
#   VM_REFCNT_EXCLUDE_READERS_FLAG replaces VMA_LOCK_OFFSET
#   __is_vma_write_locked() signature changed from two args to one
NV_MMAP_VMA_LOCK_PATCH = r"""--- a/nvidia/nv-mmap.c
+++ b/nvidia/nv-mmap.c
@@ -868,17 +868,24 @@

     nvl->safe_to_mmap = safe_to_mmap;
 }
+#ifndef VM_REFCNT_EXCLUDE_READERS_FLAG
+#define VM_REFCNT_EXCLUDE_READERS_FLAG VMA_LOCK_OFFSET
+#else
+#define NV_VMA_WRITE_LOCKED_ONE_ARG 1
+#endif
+
+

 #if !NV_CAN_CALL_VMA_START_WRITE
 static NvBool nv_vma_enter_locked(struct vm_area_struct *vma, NvBool detaching)
 {
-    NvU32 tgt_refcnt = VMA_LOCK_OFFSET;
+    NvU32 tgt_refcnt = VM_REFCNT_EXCLUDE_READERS_FLAG;
     NvBool interrupted = NV_FALSE;
     if (!detaching)
     {
         tgt_refcnt++;
     }
-    if (!refcount_add_not_zero(VMA_LOCK_OFFSET, &vma->vm_refcnt))
+    if (!refcount_add_not_zero(VM_REFCNT_EXCLUDE_READERS_FLAG, &vma->vm_refcnt))
     {
         return NV_FALSE;
     }
@@ -908,7 +915,7 @@
     if (interrupted)
     {
         // Clean up on error: release refcount and dep_map
-        refcount_sub_and_test(VMA_LOCK_OFFSET, &vma->vm_refcnt);
+        refcount_sub_and_test(VM_REFCNT_EXCLUDE_READERS_FLAG, &vma->vm_refcnt);
         rwsem_release(&vma->vmlock_dep_map, _RET_IP_);
         return NV_FALSE;
     }
@@ -924,7 +931,11 @@
 {
     NvU32 mm_lock_seq;
     NvBool locked;
+#ifdef NV_VMA_WRITE_LOCKED_ONE_ARG
+    if (__is_vma_write_locked(vma))
+#else
     if (__is_vma_write_locked(vma, &mm_lock_seq))
+#endif
         return;

     locked = nv_vma_enter_locked(vma, NV_FALSE);
@@ -933,7 +944,7 @@
     if (locked)
     {
         NvBool detached;
-        detached = refcount_sub_and_test(VMA_LOCK_OFFSET, &vma->vm_refcnt);
+        detached = refcount_sub_and_test(VM_REFCNT_EXCLUDE_READERS_FLAG, &vma->vm_refcnt);
         rwsem_release(&vma->vmlock_dep_map, _RET_IP_);
         WARN_ON_ONCE(detached);
     }
"""


# Fixes missing strncpy() declaration in os-interface.c on Linux 7.2+:
# some kernel header that used to transitively pull in <linux/string.h>
# stopped doing so, and NVIDIA's os_get_current_process_name() never
# included it directly. GCC now errors instead of warning on implicit
# function declarations, so the build fails outright.
NV_STRING_H_PATCH = r"""--- a/nvidia/os-interface.c
+++ b/nvidia/os-interface.c
@@ -35,6 +35,7 @@
 #include <linux/mmzone.h>
 #include <linux/numa.h>
 #include <linux/cpuset.h>
 #include <linux/sys_soc.h>
+#include <linux/string.h>

 extern char *NVreg_TemporaryFilePath;
"""


# Fixes dmem_cgroup_register_region() API change on Linux 7.3+:
# kernel commit e11640b9cea4 ("cgroup/dmem: Introduce struct dmem_cgroup_init
# for region initialization") changed the first argument from a bare u64 size
# to a const struct dmem_cgroup_init *.  NVIDIA 610 (open) passes size
# directly, which GCC rejects with -Wint-conversion on kernel 7.3+.
#
# The LINUX_VERSION_CODE guard is safe: struct dmem_cgroup_init does not exist
# on 7.2, so the #else branch keeps the old call on 7.2 and below.  The patch
# only activates inside the NV_USE_DMEM_CGROUP_API block (defined only when
# the dmem cgroup subsystem is present, i.e. Turing+ with the open driver),
# so 550/580/590 and the proprietary driver are completely unaffected.
NV_DMEM_CGROUP_INIT_PATCH = r"""--- a/nvidia/os-interface.c
+++ b/nvidia/os-interface.c
@@ -2818,7 +2818,17 @@
 void* NV_API_CALL os_dmem_cgroup_register_region(NvU64 size, const char *name)
 {
+#if LINUX_VERSION_CODE >= KERNEL_VERSION(7, 3, 0)
+    struct dmem_cgroup_init init = {
+        .size = size,
+        .ops  = NULL,
+        .reclaim_priv = NULL,
+    };
+    void *region = dmem_cgroup_register_region(&init, name);
+#else
     void *region = dmem_cgroup_register_region(size, name);
+#endif
     if (IS_ERR(region))
     {
         return NULL;
"""


def get_nvidia_dkms_patch_commands() -> str:
    """
    Return a shell script fragment that applies NVIDIA DKMS compatibility
    patches to all installed NVIDIA source trees under /usr/src/nvidia-*/.

    Safe to run on any kernel version — patches use #ifndef / LINUX_VERSION_CODE
    guards so they are no-ops on kernels that don't need them.
    Skips source trees that are already patched (idempotent).
    """
    mmap_patch = NV_MMAP_VMA_LOCK_PATCH.replace("'", "'\\''")
    string_h_patch = NV_STRING_H_PATCH.replace("'", "'\\''")
    dmem_patch = NV_DMEM_CGROUP_INIT_PATCH.replace("'", "'\\''")

    # The proprietary driver keeps its sources at <src>/nvidia/, the open kernel
    # modules (nvidia-open-590, nvidia-open-610) at <src>/kernel-open/nvidia/.
    # Checking only the first silently skipped every nvidia-open install, which
    # is now the layout used by everything Turing and newer.
    #
    # Each patch is applied independently — one file missing/already-patched
    # must not skip the check for the other file.
    return (
        "for NVIDIA_SRC in /usr/src/nvidia-*/; do "
        "  for NV_SUB in '' 'kernel-open/'; do "
        "    NV_ROOT=\"${NVIDIA_SRC}${NV_SUB}\"; "
        "    NV_MMAP=\"${NV_ROOT}nvidia/nv-mmap.c\"; "
        "    if [ -f \"$NV_MMAP\" ]; then "
        "      if grep -q 'VM_REFCNT_EXCLUDE_READERS_FLAG' \"$NV_MMAP\" 2>/dev/null; then "
        "        echo \"NVIDIA VMA patch already applied in ${NV_ROOT} — skipping.\"; "
        "      elif ! grep -q 'VMA_LOCK_OFFSET' \"$NV_MMAP\" 2>/dev/null; then "
        "        echo \"${NV_ROOT} does not use VMA_LOCK_OFFSET — patch not needed.\"; "
        "      else "
        "        echo \"Applying NVIDIA VMA lock patch to ${NV_ROOT}...\"; "
        f"        printf '%s' '{mmap_patch}' | patch --fuzz=5 -p1 -d \"$NV_ROOT\" && "
        "        echo \"NVIDIA VMA patch applied successfully.\" || "
        "        echo \"Warning: NVIDIA VMA patch failed for ${NV_ROOT} — DKMS may fail.\"; "
        "      fi; "
        "    fi; "
        "    NV_OSIF=\"${NV_ROOT}nvidia/os-interface.c\"; "
        "    if [ -f \"$NV_OSIF\" ]; then "
        "      if grep -q '#include <linux/string.h>' \"$NV_OSIF\" 2>/dev/null; then "
        "        echo \"NVIDIA string.h patch already applied in ${NV_ROOT} — skipping.\"; "
        "      else "
        "        echo \"Applying NVIDIA string.h patch to ${NV_ROOT}...\"; "
        f"        printf '%s' '{string_h_patch}' | patch --fuzz=5 -p1 -d \"$NV_ROOT\" && "
        "        echo \"NVIDIA string.h patch applied successfully.\" || "
        "        echo \"Warning: NVIDIA string.h patch failed for ${NV_ROOT} — DKMS may fail.\"; "
        "      fi; "
        "      if grep -q 'NV_USE_DMEM_CGROUP_API' \"$NV_OSIF\" 2>/dev/null; then "
        "        if grep -q 'dmem_cgroup_register_region(&init' \"$NV_OSIF\" 2>/dev/null; then "
        "          echo \"NVIDIA dmem cgroup init patch already applied in ${NV_ROOT} — skipping.\"; "
        "        elif grep -q 'dmem_cgroup_register_region(size' \"$NV_OSIF\" 2>/dev/null; then "
        "          echo \"Applying NVIDIA dmem cgroup init patch to ${NV_ROOT}...\"; "
        f"          printf '%s' '{dmem_patch}' | patch --fuzz=5 -p1 -d \"$NV_ROOT\" && "
        "          echo \"NVIDIA dmem cgroup init patch applied successfully.\" || "
        "          echo \"Warning: NVIDIA dmem cgroup init patch failed for ${NV_ROOT} — DKMS may fail.\"; "
        "        fi; "
        "      fi; "
        "    fi; "
        "  done; "
        "done"
    )
