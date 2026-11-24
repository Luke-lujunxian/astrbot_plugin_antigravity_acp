<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue';
import { copyTextSafely } from '@/utils/copy';
import { mdiCheck, mdiContentCopy } from '@/utils/icons';

const props = withDefaults(
  defineProps<{
    modelValue: string;
    label?: string;
    buttonLabel?: string;
    ariaLabel?: string;
    placeholder?: string;
    isDisposed?: () => boolean;
  }>(),
  {
    label: '',
    buttonLabel: '复制',
    ariaLabel: '',
    placeholder: '',
    isDisposed: undefined,
  },
);

const emit = defineEmits<{
  (e: 'notify', payload: { text: string; color: 'success' | 'warning' }): void;
}>();

const inputRef = ref<HTMLInputElement | null>(null);
const buttonElRef = ref<HTMLElement | null>(null);
const feedbackState = ref<'idle' | 'copied' | 'manual'>('idle');
let resetTimer: ReturnType<typeof setTimeout> | null = null;

function clearResetTimer(): void {
  if (resetTimer) {
    clearTimeout(resetTimer);
    resetTimer = null;
  }
}

async function handleCopy(): Promise<void> {
  const text = props.modelValue;
  if (!text) return;

  const outcome = await copyTextSafely(text, {
    sourceInput: inputRef.value,
    returnFocusEl: buttonElRef.value,
    isDisposed: props.isDisposed,
  });

  if (outcome === 'empty' || outcome === 'stale') return;

  clearResetTimer();
  feedbackState.value = outcome === 'copied' ? 'copied' : 'manual';
  emit('notify', {
    text: outcome === 'copied' ? '已复制' : '已选中，请按 Ctrl+C / ⌘C 复制',
    color: outcome === 'copied' ? 'success' : 'warning',
  });

  resetTimer = setTimeout(() => {
    feedbackState.value = 'idle';
    resetTimer = null;
  }, 2000);
}

onBeforeUnmount(() => {
  clearResetTimer();
});
</script>

<template>
  <div class="d-flex flex-column ga-1">
    <label v-if="label" class="text-body-2 font-weight-medium text-medium-emphasis">
      {{ label }}
    </label>
    <div class="agy-copy-input-wrap">
      <input
        ref="inputRef"
        :value="modelValue"
        :aria-label="ariaLabel || label || '可复制内容'"
        :placeholder="placeholder"
        class="agy-copy-input"
        readonly
        autocomplete="off"
        spellcheck="false"
      />
      <span ref="buttonElRef" class="d-inline-flex ga-2 align-center">
        <v-btn
          size="small"
          :color="feedbackState === 'copied' ? 'success' : feedbackState === 'manual' ? 'warning' : 'primary'"
          :variant="feedbackState === 'idle' ? 'tonal' : 'flat'"
          :disabled="!modelValue"
          :prepend-icon="feedbackState === 'copied' ? mdiCheck : mdiContentCopy"
          @click="handleCopy"
        >
          {{
            feedbackState === 'copied'
              ? '已复制 ✓'
              : feedbackState === 'manual'
                ? '请手动复制'
                : buttonLabel
          }}
        </v-btn>
        <slot name="append" />
      </span>
    </div>
  </div>
</template>
