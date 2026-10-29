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
@@ -2818,6 +2818,15 @@
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


# NVIDIA 550 (Debian nvidia-kernel-dkms, 550.163.01) on kernels 7.2+: linux/of_gpio.h
# was removed in 7.1, strncpy() in 7.2, and struct drm_atomic_state became
# struct drm_atomic_commit in 7.2.  The patch adds the of_gpio.h compat block that
# NVIDIA 610 already carries, replaces the five strncpy() calls, maps the renamed
# DRM names and forces five nvidia-drm configure-time probes.  Same patch as
# nvidia-patches/patches/nvidia-550-kernel7.2-compat.patch.
#
# It is only applied when the tree still has the 550 text (unguarded of_gpio.h
# include and the strncpy() in os_get_current_process_name) and a dry run
# succeeds, so 580/590/610 and trees that are already patched are untouched.
NV_550_KERNEL72_COMPAT_PATCH = r"""--- a/common/inc/nv-linux.h
+++ b/common/inc/nv-linux.h
@@ -2038,7 +2038,71 @@
 #endif
 
 #if defined(NV_LINUX_OF_GPIO_H_PRESENT)
+#if __has_include(<linux/of_gpio.h>)
 #include <linux/of_gpio.h>
+#else
+#include <linux/gpio/driver.h>
+
+static inline int __to_hwgpio(const struct gpio_device *gdev,
+                              const struct of_phandle_args *gpiospec)
+{
+#if defined(CONFIG_OF_GPIO)
+    /*
+     * Use the chip's of_xlate callback to translate the DT GPIO
+     * specifier into a linear offset.  Tegra GPIO controllers encode
+     * port and pin in args[0] and of_xlate sums per-port pin counts
+     * to produce the real offset.
+     */
+    struct gpio_chip *chip = gpio_device_get_chip(gdev);
+
+    if (chip->of_xlate)
+        return chip->of_xlate(chip, gpiospec, NULL);
+#endif
+
+    return gpiospec->args[0];
+}
+
+/*
+ * of_get_named_gpio() was removed along with linux/of_gpio.h by commit
+ * 51aaf65bbd21 ("gpio: of: Remove <linux/of_gpio.h>"). Provide a compat
+ * implementation using the remaining public GPIO APIs.
+ */
+static inline int of_get_named_gpio(const struct device_node *np,
+                                    const char *propname, int index)
+{
+    struct of_phandle_args gpiospec;
+    struct gpio_device *gdev;
+    struct gpio_desc *desc;
+    int ret, hwgpio;
+
+    if (!np)
+        return -ENOENT;
+
+    ret =
+        of_parse_phandle_with_args_map(np, propname, "gpio", index, &gpiospec);
+    if (ret)
+        return ret;
+
+    gdev = gpio_device_find_by_fwnode(of_fwnode_handle(gpiospec.np));
+    of_node_put(gpiospec.np);
+    if (!gdev)
+        return -EPROBE_DEFER;
+
+    hwgpio = __to_hwgpio(gdev, &gpiospec);
+    if (hwgpio < 0) {
+        gpio_device_put(gdev);
+        return hwgpio;
+    }
+
+    desc = gpio_device_get_desc(gdev, hwgpio);
+    gpio_device_put(gdev);
+
+    if (IS_ERR(desc))
+        return PTR_ERR(desc);
+
+    return desc_to_gpio(desc);
+}
+#endif
 #endif
 
 #if defined(NV_LINUX_OF_DEVICE_H_PRESENT)
--- a/nvidia/os-interface.c
+++ b/nvidia/os-interface.c
@@ -750,8 +750,9 @@
 void NV_API_CALL os_get_current_process_name(char *buf, NvU32 len)
 {
     task_lock(current);
-    strncpy(buf, current->comm, len - 1);
-    buf[len - 1] = '\0';
+    if (strscpy(buf, current->comm, len) < 0) {
+        // strscpy() returns -E2BIG on truncation, which is acceptable here.
+    }
     task_unlock(current);
 }
 
--- a/nvidia/linux_nvswitch.c
+++ b/nvidia/linux_nvswitch.c
@@ -2026,7 +2026,7 @@
         return -NVL_ERR_GENERIC;
     }
 
-    strncpy(regkey_val, regkey_val_start, regkey_val_len);
+    memcpy(regkey_val, regkey_val_start, regkey_val_len);
     regkey_val[regkey_val_len] = '\0';
 
     if (nvswitch_os_strtouint(regkey_val, data) != 0)
@@ -2381,7 +2381,13 @@
     NvLength length
 )
 {
-    return strncpy(dest, src, length);
+    NvLength i;
+
+    for (i = 0; i < length && src[i] != '\0'; i++)
+        dest[i] = src[i];
+    for (; i < length; i++)
+        dest[i] = '\0';
+    return dest;
 }
 
 int
--- a/nvidia-modeset/nvidia-modeset-linux.c
+++ b/nvidia-modeset/nvidia-modeset-linux.c
@@ -351,7 +351,13 @@
 
 char* nvkms_strncpy(char *dest, const char *src, size_t n)
 {
-    return strncpy(dest, src, n);
+    size_t i;
+
+    for (i = 0; i < n && src[i] != '\0'; i++)
+        dest[i] = src[i];
+    for (; i < n; i++)
+        dest[i] = '\0';
+    return dest;
 }
 
 void nvkms_usleep(NvU64 usec)
--- a/nvidia-uvm/uvm_pmm_gpu.c
+++ b/nvidia-uvm/uvm_pmm_gpu.c
@@ -3038,7 +3038,7 @@
             size_t size;
             size_t align;
             if (level == 0) {
-                strncpy(chunk_split_cache[level].name, "uvm_gpu_chunk_t", sizeof(chunk_split_cache[level].name) - 1);
+                strscpy(chunk_split_cache[level].name, "uvm_gpu_chunk_t", sizeof(chunk_split_cache[level].name));
                 size = sizeof(uvm_gpu_chunk_t);
                 align = __alignof__(uvm_gpu_chunk_t);
             } else {
--- a/nvidia-drm/nvidia-drm-conftest.h
+++ b/nvidia-drm/nvidia-drm-conftest.h
@@ -215,4 +215,41 @@
 
 #endif /* defined(NV_BSD) */
 
+/*
+ * Linux 7.2 renamed struct drm_atomic_state to struct drm_atomic_commit and
+ * the helpers that operate on it. Map the old names onto the new ones.
+ */
+#include <linux/version.h>
+#if LINUX_VERSION_CODE >= KERNEL_VERSION(7, 2, 0)
+#define drm_atomic_state                        drm_atomic_commit
+#define drm_atomic_state_alloc                  drm_atomic_commit_alloc
+#define drm_atomic_state_get                    drm_atomic_commit_get
+#define drm_atomic_state_put                    drm_atomic_commit_put
+#define drm_atomic_state_free                   drm_atomic_commit_put
+#define drm_atomic_state_clear                  drm_atomic_commit_clear
+#define drm_atomic_state_default_clear          drm_atomic_commit_default_clear
+#define drm_atomic_state_default_release        drm_atomic_commit_default_release
+#define drm_atomic_state_init                   drm_atomic_commit_init
+
+/*
+ * The configure-time probes below look for struct drm_atomic_state, which no
+ * longer exists, so they report the pre-7.2 behavior. Force the 7.2 behavior.
+ */
+#if !defined(NV_DRM_PLANE_ATOMIC_CHECK_HAS_ATOMIC_STATE_ARG)
+#define NV_DRM_PLANE_ATOMIC_CHECK_HAS_ATOMIC_STATE_ARG
+#endif
+#if !defined(NV_DRM_CRTC_ATOMIC_CHECK_HAS_ATOMIC_STATE_ARG)
+#define NV_DRM_CRTC_ATOMIC_CHECK_HAS_ATOMIC_STATE_ARG
+#endif
+#if !defined(NV_DRM_ATOMIC_STATE_REF_COUNTING_PRESENT)
+#define NV_DRM_ATOMIC_STATE_REF_COUNTING_PRESENT
+#endif
+#if !defined(NV_DRM_ATOMIC_HELPER_SWAP_STATE_HAS_STALL_ARG)
+#define NV_DRM_ATOMIC_HELPER_SWAP_STATE_HAS_STALL_ARG
+#endif
+#if !defined(NV_DRM_ATOMIC_HELPER_SWAP_STATE_RETURN_INT)
+#define NV_DRM_ATOMIC_HELPER_SWAP_STATE_RETURN_INT
+#endif
+#endif
+
 #endif /* defined(__NVIDIA_DRM_CONFTEST_H__) */
"""


# NVIDIA 590 open modules (590.48.01, nvidia-open-590) on kernels 7.2+: the same
# of_gpio.h / strncpy() / DRM atomic commit fixes as the 550 patch above, plus the
# nvidia-uvm changes NVIDIA 610 already carries (dev_pagemap_ops page_free became
# folio_free, and zone_device_page_init() takes the pgmap and an order), backported
# through two conftest.sh probes.  Applied from kernel-open/ after the VMA patch.
# Same patch as nvidia-patches/patches/nvidia-590-kernel7.2-compat.patch.
NV_590_KERNEL72_COMPAT_PATCH = r"""--- a/common/inc/nv-linux.h
+++ b/common/inc/nv-linux.h
@@ -1714,7 +1714,71 @@
 #include <linux/reset.h>
 #include <linux/dma-buf.h>
 #include <linux/gpio.h>
+#if __has_include(<linux/of_gpio.h>)
 #include <linux/of_gpio.h>
+#else
+#include <linux/gpio/driver.h>
+
+static inline int __to_hwgpio(const struct gpio_device *gdev,
+                              const struct of_phandle_args *gpiospec)
+{
+#if defined(CONFIG_OF_GPIO)
+    /*
+     * Use the chip's of_xlate callback to translate the DT GPIO
+     * specifier into a linear offset.  Tegra GPIO controllers encode
+     * port and pin in args[0] and of_xlate sums per-port pin counts
+     * to produce the real offset.
+     */
+    struct gpio_chip *chip = gpio_device_get_chip(gdev);
+
+    if (chip->of_xlate)
+        return chip->of_xlate(chip, gpiospec, NULL);
+#endif
+
+    return gpiospec->args[0];
+}
+
+/*
+ * of_get_named_gpio() was removed along with linux/of_gpio.h by commit
+ * 51aaf65bbd21 ("gpio: of: Remove <linux/of_gpio.h>"). Provide a compat
+ * implementation using the remaining public GPIO APIs.
+ */
+static inline int of_get_named_gpio(const struct device_node *np,
+                                    const char *propname, int index)
+{
+    struct of_phandle_args gpiospec;
+    struct gpio_device *gdev;
+    struct gpio_desc *desc;
+    int ret, hwgpio;
+
+    if (!np)
+        return -ENOENT;
+
+    ret =
+        of_parse_phandle_with_args_map(np, propname, "gpio", index, &gpiospec);
+    if (ret)
+        return ret;
+
+    gdev = gpio_device_find_by_fwnode(of_fwnode_handle(gpiospec.np));
+    of_node_put(gpiospec.np);
+    if (!gdev)
+        return -EPROBE_DEFER;
+
+    hwgpio = __to_hwgpio(gdev, &gpiospec);
+    if (hwgpio < 0) {
+        gpio_device_put(gdev);
+        return hwgpio;
+    }
+
+    desc = gpio_device_get_desc(gdev, hwgpio);
+    gpio_device_put(gdev);
+
+    if (IS_ERR(desc))
+        return PTR_ERR(desc);
+
+    return desc_to_gpio(desc);
+}
+#endif
 #include <linux/of_device.h>
 #include <linux/of_platform.h>
 
--- a/nvidia/os-interface.c
+++ b/nvidia/os-interface.c
@@ -759,8 +759,9 @@
 void NV_API_CALL os_get_current_process_name(char *buf, NvU32 len)
 {
     task_lock(current);
-    strncpy(buf, current->comm, len - 1);
-    buf[len - 1] = '\0';
+    if (strscpy(buf, current->comm, len) < 0) {
+        // strscpy() returns -E2BIG on truncation, which is acceptable here.
+    }
     task_unlock(current);
 }
 
--- a/nvidia/linux_nvswitch.c
+++ b/nvidia/linux_nvswitch.c
@@ -2059,7 +2059,7 @@
         return -NVL_ERR_GENERIC;
     }
 
-    strncpy(regkey_val, regkey_val_start, regkey_val_len);
+    memcpy(regkey_val, regkey_val_start, regkey_val_len);
     regkey_val[regkey_val_len] = '\0';
 
     if (nvswitch_os_strtouint(regkey_val, data) != 0)
@@ -2414,7 +2414,13 @@
     NvLength length
 )
 {
-    return strncpy(dest, src, length);
+    NvLength i;
+
+    for (i = 0; i < length && src[i] != '\0'; i++)
+        dest[i] = src[i];
+    for (; i < length; i++)
+        dest[i] = '\0';
+    return dest;
 }
 
 int
--- a/nvidia-modeset/nvidia-modeset-linux.c
+++ b/nvidia-modeset/nvidia-modeset-linux.c
@@ -647,7 +647,13 @@
 
 char* nvkms_strncpy(char *dest, const char *src, size_t n)
 {
-    return strncpy(dest, src, n);
+    size_t i;
+
+    for (i = 0; i < n && src[i] != '\0'; i++)
+        dest[i] = src[i];
+    for (; i < n; i++)
+        dest[i] = '\0';
+    return dest;
 }
 
 void nvkms_usleep(NvU64 usec)
--- a/nvidia-uvm/uvm_pmm_gpu.c
+++ b/nvidia-uvm/uvm_pmm_gpu.c
@@ -2786,7 +2786,7 @@
             size_t size;
             size_t align;
             if (level == 0) {
-                strncpy(chunk_split_cache[level].name, "uvm_gpu_chunk_t", sizeof(chunk_split_cache[level].name) - 1);
+                strscpy(chunk_split_cache[level].name, "uvm_gpu_chunk_t", sizeof(chunk_split_cache[level].name));
                 size = sizeof(uvm_gpu_chunk_t);
                 align = __alignof__(uvm_gpu_chunk_t);
             } else {
@@ -3058,9 +3058,20 @@
     UVM_ENTRY_RET(devmem_fault(vmf));
 }
 
+#if defined(NV_PAGEMAP_OPS_HAS_FOLIO_FREE)
+static void devmem_folio_free(struct folio *folio)
+{
+    devmem_page_free(&folio->page);
+}
+#endif
+
 static const struct dev_pagemap_ops uvm_pmm_devmem_ops =
 {
+#if defined(NV_PAGEMAP_OPS_HAS_FOLIO_FREE)
+    .folio_free = devmem_folio_free,
+#else
     .page_free = devmem_page_free,
+#endif
     .migrate_to_ram = devmem_fault_entry,
 };
 
@@ -3163,9 +3174,20 @@
     device_p2p_page_free(page);
 }
 
+#if defined(NV_PAGEMAP_OPS_HAS_FOLIO_FREE)
+static void device_coherent_folio_free(struct folio *folio)
+{
+    device_coherent_page_free(&folio->page);
+}
+#endif
+
 static const struct dev_pagemap_ops uvm_device_coherent_pgmap_ops =
 {
+#if defined(NV_PAGEMAP_OPS_HAS_FOLIO_FREE)
+    .folio_free = device_coherent_folio_free,
+#else
     .page_free = device_coherent_page_free,
+#endif
 };
 
 static NV_STATUS uvm_pmm_cdmm_init(uvm_parent_gpu_t *parent_gpu)
@@ -3300,9 +3322,20 @@
 // ARM
 #if defined(CONFIG_PCI_P2PDMA) && defined(NV_STRUCT_PAGE_HAS_ZONE_DEVICE_DATA) && !defined(NVCPU_AARCH64)
 
+#if defined(NV_PAGEMAP_OPS_HAS_FOLIO_FREE)
+static void device_p2p_folio_free(struct folio *folio)
+{
+    device_p2p_page_free(&folio->page);
+}
+#endif
+
 static const struct dev_pagemap_ops uvm_device_p2p_pgmap_ops =
 {
+#if defined(NV_PAGEMAP_OPS_HAS_FOLIO_FREE)
+    .folio_free = device_p2p_folio_free,
+#else
     .page_free = device_p2p_page_free,
+#endif
 };
 
 void uvm_pmm_gpu_device_p2p_init(uvm_parent_gpu_t *parent_gpu)
--- a/nvidia-uvm/uvm_hmm.c
+++ b/nvidia-uvm/uvm_hmm.c
@@ -74,6 +74,19 @@
 #include "uvm_va_policy.h"
 #include "uvm_tools.h"
 
+//
+// Pass 0 as the order, when actual large order support is added this
+// function will need to be revisited
+//
+static __always_inline void nv_zone_device_page_init(struct page *page)
+{
+#if defined(NV_ZONE_DEVICE_PAGE_INIT_HAS_PGMAP_AND_ORDER_ARGS)
+    zone_device_page_init(page, page_pgmap(page), 0);
+#else
+    zone_device_page_init(page);
+#endif
+}
+
 // The function nv_PageSwapCache() wraps the check for page swap cache flag in
 // order to support a wide variety of kernel versions.
 // The function PageSwapCache() is removed after 32f51ead3d77 ("mm: remove
@@ -2140,7 +2153,7 @@
 
         UVM_ASSERT(!page_count(dpage));
         UVM_ASSERT(!dpage->zone_device_data);
-        zone_device_page_init(dpage);
+        nv_zone_device_page_init(dpage);
         dpage->zone_device_data = gpu_chunk;
         atomic64_inc(&va_block->hmm.va_space->hmm.allocated_page_count);
     }
--- a/nvidia-uvm/nvidia-uvm.Kbuild
+++ b/nvidia-uvm/nvidia-uvm.Kbuild
@@ -68,6 +68,8 @@
 NV_CONFTEST_TYPE_COMPILE_TESTS += mmu_interval_notifier
 NV_CONFTEST_TYPE_COMPILE_TESTS += sg_dma_page_iter
 NV_CONFTEST_TYPE_COMPILE_TESTS += struct_page_has_zone_device_data
+NV_CONFTEST_TYPE_COMPILE_TESTS += dev_pagemap_ops_has_folio_free
+NV_CONFTEST_TYPE_COMPILE_TESTS += zone_device_page_init_has_pgmap_and_order_args
 NV_CONFTEST_TYPE_COMPILE_TESTS += memory_device_coherent_present
 
 NV_CONFTEST_SYMBOL_COMPILE_TESTS += is_export_symbol_present_int_active_memcg
--- a/nvidia-drm/nvidia-drm-conftest.h
+++ b/nvidia-drm/nvidia-drm-conftest.h
@@ -207,4 +207,41 @@
 
 #endif /* defined(NV_BSD) */
 
+/*
+ * Linux 7.2 renamed struct drm_atomic_state to struct drm_atomic_commit and
+ * the helpers that operate on it. Map the old names onto the new ones.
+ */
+#include <linux/version.h>
+#if LINUX_VERSION_CODE >= KERNEL_VERSION(7, 2, 0)
+#define drm_atomic_state                        drm_atomic_commit
+#define drm_atomic_state_alloc                  drm_atomic_commit_alloc
+#define drm_atomic_state_get                    drm_atomic_commit_get
+#define drm_atomic_state_put                    drm_atomic_commit_put
+#define drm_atomic_state_free                   drm_atomic_commit_put
+#define drm_atomic_state_clear                  drm_atomic_commit_clear
+#define drm_atomic_state_default_clear          drm_atomic_commit_default_clear
+#define drm_atomic_state_default_release        drm_atomic_commit_default_release
+#define drm_atomic_state_init                   drm_atomic_commit_init
+
+/*
+ * The configure-time probes below look for struct drm_atomic_state, which no
+ * longer exists, so they report the pre-7.2 behavior. Force the 7.2 behavior.
+ */
+#if !defined(NV_DRM_PLANE_ATOMIC_CHECK_HAS_ATOMIC_STATE_ARG)
+#define NV_DRM_PLANE_ATOMIC_CHECK_HAS_ATOMIC_STATE_ARG
+#endif
+#if !defined(NV_DRM_CRTC_ATOMIC_CHECK_HAS_ATOMIC_STATE_ARG)
+#define NV_DRM_CRTC_ATOMIC_CHECK_HAS_ATOMIC_STATE_ARG
+#endif
+#if !defined(NV_DRM_ATOMIC_STATE_REF_COUNTING_PRESENT)
+#define NV_DRM_ATOMIC_STATE_REF_COUNTING_PRESENT
+#endif
+#if !defined(NV_DRM_ATOMIC_HELPER_SWAP_STATE_HAS_STALL_ARG)
+#define NV_DRM_ATOMIC_HELPER_SWAP_STATE_HAS_STALL_ARG
+#endif
+#if !defined(NV_DRM_ATOMIC_HELPER_SWAP_STATE_RETURN_INT)
+#define NV_DRM_ATOMIC_HELPER_SWAP_STATE_RETURN_INT
+#endif
+#endif
+
 #endif /* defined(__NVIDIA_DRM_CONFTEST_H__) */
--- a/conftest.sh
+++ b/conftest.sh
@@ -4747,6 +4747,56 @@
             compile_check_conftest "$CODE" "NV_DRM_APERTURE_REMOVE_CONFLICTING_FRAMEBUFFERS_HAS_NO_PRIMARY_ARG" "" "types"
         ;;
 
+        zone_device_page_init_has_pgmap_and_order_args)
+            #
+            # Determine if the zone_device_page_init() has two additional
+            # arguments
+            #
+            # This change was introduced by d245f9b4ab80
+            # ("mm/zone_device: support large zone device private folios")
+            #
+            # It was further amended in 9387a71ec62c
+            # (mm/zone_device: reinitialize large zone device private folios)
+            #
+            # both commits are in linux-next, expected in v6.19.
+            #
+            CODE="
+            #include <linux/memremap.h>
+
+            void init_page(void) {
+                struct page *page;
+                struct dev_pagemap *pgmap;
+
+                zone_device_page_init(page, pgmap, 0);
+            }"
+
+            compile_check_conftest "$CODE" "NV_ZONE_DEVICE_PAGE_INIT_HAS_PGMAP_AND_ORDER_ARGS" "" "types"
+        ;;
+
+        dev_pagemap_ops_has_folio_free)
+            #
+            # Determine if the zone device now uses a folio_free() as the callback
+            # function instead of page_free()
+            #
+            # This change was introduced by 3a5a06554566
+            # (mm/zone_device: rename page_free callback to folio_free)
+            #
+            # in linux-next, expected in v6.19.
+            #
+            CODE="
+            #include <linux/memremap.h>
+
+            void test_folio_free(struct folio *folio) {
+            }
+
+            void set_folio_free_ops(void) {
+                struct dev_pagemap_ops ops;
+                ops.folio_free = test_folio_free;
+            }"
+
+            compile_check_conftest "$CODE" "NV_PAGEMAP_OPS_HAS_FOLIO_FREE" "" "types"
+        ;;
+
         struct_page_has_zone_device_data)
             #
             # Determine if struct page has a 'zone_device_data' field.
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
    compat550_patch = NV_550_KERNEL72_COMPAT_PATCH.replace("'", "'\\''")
    compat590_patch = NV_590_KERNEL72_COMPAT_PATCH.replace("'", "'\\''")

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
        f"        NV_PVMA='{mmap_patch}'; "
        # Dry run first: a patch that only half applies would leave the
        # source tree under /usr/src broken for every later DKMS build.
        "        if printf '%s' \"$NV_PVMA\" | patch --fuzz=5 -p1 -d \"$NV_ROOT\" --dry-run > /dev/null 2>&1; then "
        "          echo \"Applying NVIDIA VMA lock patch to ${NV_ROOT}...\"; "
        "          printf '%s' \"$NV_PVMA\" | patch --fuzz=5 -p1 -d \"$NV_ROOT\" && "
        "          echo \"NVIDIA VMA patch applied successfully.\" || "
        "          echo \"Warning: NVIDIA VMA patch failed for ${NV_ROOT} — DKMS may fail.\"; "
        "        else "
        "          echo \"Warning: NVIDIA VMA patch does not apply cleanly to ${NV_ROOT} — left untouched, DKMS may fail.\"; "
        "        fi; "
        "      fi; "
        "    fi; "
        "    NV_OSIF=\"${NV_ROOT}nvidia/os-interface.c\"; "
        "    if [ -f \"$NV_OSIF\" ]; then "
        "      if grep -q '#include <linux/string.h>' \"$NV_OSIF\" 2>/dev/null; then "
        "        echo \"NVIDIA string.h patch already applied in ${NV_ROOT} — skipping.\"; "
        "      else "
        f"        NV_PSTR='{string_h_patch}'; "
        "        if printf '%s' \"$NV_PSTR\" | patch --fuzz=5 -p1 -d \"$NV_ROOT\" --dry-run > /dev/null 2>&1; then "
        "          echo \"Applying NVIDIA string.h patch to ${NV_ROOT}...\"; "
        "          printf '%s' \"$NV_PSTR\" | patch --fuzz=5 -p1 -d \"$NV_ROOT\" && "
        "          echo \"NVIDIA string.h patch applied successfully.\" || "
        "          echo \"Warning: NVIDIA string.h patch failed for ${NV_ROOT} — DKMS may fail.\"; "
        "        else "
        "          echo \"Warning: NVIDIA string.h patch does not apply cleanly to ${NV_ROOT} — left untouched, DKMS may fail.\"; "
        "        fi; "
        "      fi; "
        "      if grep -q 'NV_USE_DMEM_CGROUP_API' \"$NV_OSIF\" 2>/dev/null; then "
        "        if grep -q 'dmem_cgroup_register_region(&init' \"$NV_OSIF\" 2>/dev/null; then "
        "          echo \"NVIDIA dmem cgroup init patch already applied in ${NV_ROOT} — skipping.\"; "
        "        elif grep -q 'dmem_cgroup_register_region(size' \"$NV_OSIF\" 2>/dev/null; then "
        f"          NV_PDMEM='{dmem_patch}'; "
        "          if printf '%s' \"$NV_PDMEM\" | patch --fuzz=5 -p1 -d \"$NV_ROOT\" --dry-run > /dev/null 2>&1; then "
        "            echo \"Applying NVIDIA dmem cgroup init patch to ${NV_ROOT}...\"; "
        "            printf '%s' \"$NV_PDMEM\" | patch --fuzz=5 -p1 -d \"$NV_ROOT\" && "
        "            echo \"NVIDIA dmem cgroup init patch applied successfully.\" || "
        "            echo \"Warning: NVIDIA dmem cgroup init patch failed for ${NV_ROOT} — DKMS may fail.\"; "
        "          else "
        "            echo \"Warning: NVIDIA dmem cgroup init patch does not apply cleanly to ${NV_ROOT} — left untouched, DKMS may fail.\"; "
        "          fi; "
        "        fi; "
        "      fi; "
        "    fi; "
        "    NV_LINUXH=\"${NV_ROOT}common/inc/nv-linux.h\"; "
        "    if [ -f \"$NV_LINUXH\" ] && [ -f \"$NV_OSIF\" ] && "
        "       grep -q 'NV_LINUX_OF_GPIO_H_PRESENT' \"$NV_LINUXH\" 2>/dev/null && "
        "       grep -q '^#include <linux/of_gpio.h>' \"$NV_LINUXH\" 2>/dev/null && "
        "       ! grep -q '__has_include(<linux/of_gpio.h>)' \"$NV_LINUXH\" 2>/dev/null && "
        "       grep -q 'strncpy(buf, current->comm, len - 1)' \"$NV_OSIF\" 2>/dev/null; then "
        f"      NV_P550='{compat550_patch}'; "
        "      if printf '%s' \"$NV_P550\" | patch --fuzz=5 -p1 -d \"$NV_ROOT\" --dry-run > /dev/null 2>&1; then "
        "        echo \"Applying NVIDIA 550 kernel 7.2+ compatibility patch to ${NV_ROOT}...\"; "
        "        printf '%s' \"$NV_P550\" | patch --fuzz=5 -p1 -d \"$NV_ROOT\" && "
        "        echo \"NVIDIA 550 compatibility patch applied successfully.\" || "
        "        echo \"Warning: NVIDIA 550 compatibility patch failed for ${NV_ROOT} — DKMS may fail.\"; "
        "      else "
        "        echo \"Warning: NVIDIA 550 compatibility patch does not apply cleanly to ${NV_ROOT} — DKMS may fail.\"; "
        "      fi; "
        "    fi; "
        "    NV_UVMHMM=\"${NV_ROOT}nvidia-uvm/uvm_hmm.c\"; "
        "    if [ -f \"$NV_LINUXH\" ] && [ -f \"$NV_OSIF\" ] && [ -f \"$NV_UVMHMM\" ] && "
        "       ! grep -q 'NV_LINUX_OF_GPIO_H_PRESENT' \"$NV_LINUXH\" 2>/dev/null && "
        "       grep -q '^#include <linux/of_gpio.h>' \"$NV_LINUXH\" 2>/dev/null && "
        "       ! grep -q '__has_include(<linux/of_gpio.h>)' \"$NV_LINUXH\" 2>/dev/null && "
        "       grep -q 'strncpy(buf, current->comm, len - 1)' \"$NV_OSIF\" 2>/dev/null; then "
        f"      NV_P590='{compat590_patch}'; "
        "      if printf '%s' \"$NV_P590\" | patch --fuzz=5 -p1 -d \"$NV_ROOT\" --dry-run > /dev/null 2>&1; then "
        "        echo \"Applying NVIDIA 590 kernel 7.2+ compatibility patch to ${NV_ROOT}...\"; "
        "        printf '%s' \"$NV_P590\" | patch --fuzz=5 -p1 -d \"$NV_ROOT\" && "
        "        echo \"NVIDIA 590 compatibility patch applied successfully.\" || "
        "        echo \"Warning: NVIDIA 590 compatibility patch failed for ${NV_ROOT} — DKMS may fail.\"; "
        "      else "
        "        echo \"Warning: NVIDIA 590 compatibility patch does not apply cleanly to ${NV_ROOT} — DKMS may fail.\"; "
        "      fi; "
        "    fi; "
        "  done; "
        "done"
    )
