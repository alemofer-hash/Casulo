use core::cell::UnsafeCell;
use core::mem::MaybeUninit;
use core::sync::atomic::{AtomicU8, Ordering};

/// Minimal no_std one-time cell for immutable descriptor tables.
pub struct Once<T> {
    state: AtomicU8,
    value: UnsafeCell<MaybeUninit<T>>,
}

unsafe impl<T: Send + Sync> Sync for Once<T> {}

impl<T> Once<T> {
    pub const fn new() -> Self {
        Self {
            state: AtomicU8::new(0),
            value: UnsafeCell::new(MaybeUninit::uninit()),
        }
    }

    pub fn call_once(&self, initializer: impl FnOnce() -> T) -> &T {
        if self
            .state
            .compare_exchange(0, 1, Ordering::Acquire, Ordering::Acquire)
            .is_ok()
        {
            unsafe { (*self.value.get()).write(initializer()) };
            self.state.store(2, Ordering::Release);
        } else {
            while self.state.load(Ordering::Acquire) != 2 {
                core::hint::spin_loop();
            }
        }
        unsafe { (&*self.value.get()).assume_init_ref() }
    }

    pub fn get(&self) -> Option<&T> {
        if self.state.load(Ordering::Acquire) == 2 {
            Some(unsafe { (&*self.value.get()).assume_init_ref() })
        } else {
            None
        }
    }
}
