<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="isOpen && backlogItem" class="modal-overlay" @click="close">
        <div class="modal-container" role="dialog" aria-modal="true" @click.stop>
          <div class="modal-header">
            <div>
              <h3 class="modal-title">
                {{ mode === 'create' ? t('purchaseOrder.createTitle') : t('purchaseOrder.viewTitle') }}
              </h3>
              <p class="modal-subtitle">
                {{ t('purchaseOrder.forItem', { order: backlogItem.order_id, sku: backlogItem.item_sku }) }}
              </p>
            </div>
            <button class="close-button" :aria-label="t('purchaseOrder.close')" @click="close">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M15 5L5 15M5 5L15 15" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>
          </div>

          <!-- Create mode: a form prefilled with the shortage quantity -->
          <form v-if="mode === 'create'" class="modal-body" @submit.prevent="submit">
            <div v-if="submitError" class="error-banner" role="alert">{{ submitError }}</div>

            <label class="field">
              <span>{{ t('purchaseOrder.supplier') }}</span>
              <input v-model="form.supplier_name" type="text" required maxlength="120"
                     :placeholder="t('purchaseOrder.supplierPlaceholder')" />
            </label>

            <div class="field-row">
              <label class="field">
                <span>{{ t('purchaseOrder.quantity') }}</span>
                <input v-model.number="form.quantity" type="number" min="1" step="1" required />
              </label>
              <label class="field">
                <span>{{ t('purchaseOrder.unitCost') }}</span>
                <input v-model.number="form.unit_cost" type="number" min="0.01" step="0.01" required />
              </label>
            </div>

            <label class="field">
              <span>{{ t('purchaseOrder.expectedDelivery') }}</span>
              <input v-model="form.expected_delivery_date" type="date" :min="today" required />
            </label>

            <label class="field">
              <span>{{ t('purchaseOrder.notes') }}</span>
              <textarea v-model="form.notes" rows="2" maxlength="500"
                        :placeholder="t('purchaseOrder.notesPlaceholder')"></textarea>
            </label>

            <div class="total-row">
              <span>{{ t('purchaseOrder.total') }}</span>
              <strong>{{ formatCurrencyWithDecimals(orderTotal, currentCurrency, 2) }}</strong>
            </div>

            <div class="modal-actions">
              <button type="button" class="btn secondary" @click="close">{{ t('purchaseOrder.cancel') }}</button>
              <button type="submit" class="btn primary" :disabled="submitting || !formValid">
                {{ submitting ? t('purchaseOrder.submitting') : t('purchaseOrder.submit') }}
              </button>
            </div>
          </form>

          <!-- View mode: details of the existing purchase order -->
          <div v-else class="modal-body">
            <div v-if="loadingPO" class="muted">{{ t('purchaseOrder.loading') }}</div>
            <div v-else-if="loadError" class="error-banner" role="alert">{{ loadError }}</div>
            <dl v-else-if="purchaseOrder" class="details">
              <div><dt>{{ t('purchaseOrder.poNumber') }}</dt><dd><strong>{{ purchaseOrder.id }}</strong></dd></div>
              <div><dt>{{ t('purchaseOrder.status') }}</dt><dd><span class="badge warning">{{ purchaseOrder.status }}</span></dd></div>
              <div><dt>{{ t('purchaseOrder.supplier') }}</dt><dd>{{ purchaseOrder.supplier_name }}</dd></div>
              <div><dt>{{ t('purchaseOrder.quantity') }}</dt><dd>{{ purchaseOrder.quantity.toLocaleString() }}</dd></div>
              <div><dt>{{ t('purchaseOrder.unitCost') }}</dt><dd>{{ formatCurrencyWithDecimals(purchaseOrder.unit_cost, currentCurrency, 2) }}</dd></div>
              <div><dt>{{ t('purchaseOrder.total') }}</dt><dd><strong>{{ formatCurrencyWithDecimals(purchaseOrder.quantity * purchaseOrder.unit_cost, currentCurrency, 2) }}</strong></dd></div>
              <div><dt>{{ t('purchaseOrder.expectedDelivery') }}</dt><dd>{{ purchaseOrder.expected_delivery_date }}</dd></div>
              <div><dt>{{ t('purchaseOrder.created') }}</dt><dd>{{ purchaseOrder.created_date }}</dd></div>
              <div v-if="purchaseOrder.notes" class="wide"><dt>{{ t('purchaseOrder.notes') }}</dt><dd>{{ purchaseOrder.notes }}</dd></div>
            </dl>
            <div class="modal-actions">
              <button type="button" class="btn secondary" @click="close">{{ t('purchaseOrder.close') }}</button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script>
import { ref, computed, watch } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrencyWithDecimals } from '../utils/currency'

// Default lead time suggested for a new purchase order
const DEFAULT_LEAD_DAYS = 14

const isoDate = (date) => date.toISOString().slice(0, 10)

export default {
  name: 'PurchaseOrderModal',
  props: {
    isOpen: { type: Boolean, default: false },
    backlogItem: { type: Object, default: null },
    mode: { type: String, default: 'create', validator: v => ['create', 'view'].includes(v) }
  },
  emits: ['close', 'po-created'],
  setup(props, { emit }) {
    const { t, currentCurrency } = useI18n()

    const today = isoDate(new Date())
    const emptyForm = () => ({
      supplier_name: '',
      // Default to exactly the missing quantity
      quantity: props.backlogItem
        ? Math.max(1, props.backlogItem.quantity_needed - props.backlogItem.quantity_available)
        : 1,
      unit_cost: null,
      expected_delivery_date: isoDate(new Date(Date.now() + DEFAULT_LEAD_DAYS * 86400000)),
      notes: ''
    })

    const form = ref(emptyForm())
    const submitting = ref(false)
    const submitError = ref(null)
    const purchaseOrder = ref(null)
    const loadingPO = ref(false)
    const loadError = ref(null)

    const orderTotal = computed(() => (form.value.quantity || 0) * (form.value.unit_cost || 0))
    const formValid = computed(() =>
      form.value.supplier_name.trim().length > 0 &&
      Number.isInteger(form.value.quantity) && form.value.quantity > 0 &&
      form.value.unit_cost > 0 &&
      form.value.expected_delivery_date >= today
    )

    const loadPurchaseOrder = async () => {
      try {
        loadingPO.value = true
        loadError.value = null
        purchaseOrder.value = await api.getPurchaseOrderByBacklogItem(props.backlogItem.id)
      } catch (err) {
        loadError.value = t('purchaseOrder.loadError') + ': ' + (err.response?.data?.detail || err.message)
      } finally {
        loadingPO.value = false
      }
    }

    // Reset the form or fetch the PO every time the modal opens
    watch(() => props.isOpen, (open) => {
      if (!open || !props.backlogItem) return
      submitError.value = null
      if (props.mode === 'create') {
        form.value = emptyForm()
      } else {
        purchaseOrder.value = null
        loadPurchaseOrder()
      }
    })

    const submit = async () => {
      if (!formValid.value || submitting.value) return
      try {
        submitting.value = true
        submitError.value = null
        const po = await api.createPurchaseOrder({
          backlog_item_id: props.backlogItem.id,
          supplier_name: form.value.supplier_name.trim(),
          quantity: form.value.quantity,
          unit_cost: form.value.unit_cost,
          expected_delivery_date: form.value.expected_delivery_date,
          notes: form.value.notes.trim() || null
        })
        emit('po-created', po)
      } catch (err) {
        const detail = err.response?.data?.detail
        submitError.value = t('purchaseOrder.createError') + ': ' +
          (typeof detail === 'string' ? detail : err.message)
      } finally {
        submitting.value = false
      }
    }

    const close = () => emit('close')

    return {
      t,
      currentCurrency,
      today,
      form,
      submitting,
      submitError,
      orderTotal,
      formValid,
      purchaseOrder,
      loadingPO,
      loadError,
      submit,
      close,
      formatCurrencyWithDecimals
    }
  }
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  padding: 1rem;
}

.modal-container {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.15);
  max-width: 560px;
  width: 100%;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid #e2e8f0;
}

.modal-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
}

.modal-subtitle {
  margin: 0.25rem 0 0;
  font-size: 0.875rem;
  color: #64748b;
}

.close-button {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  padding: 0.5rem;
  border-radius: 6px;
  display: flex;
}

.close-button:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.modal-body {
  overflow-y: auto;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  flex: 1;
  /* lets side-by-side fields shrink instead of overflowing the modal */
  min-width: 0;
}

.field span {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #64748b;
}

.field input,
.field textarea {
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
  font: inherit;
  color: #0f172a;
  width: 100%;
  box-sizing: border-box;
}

.field input:focus,
.field textarea:focus {
  outline: 2px solid #2563eb;
  outline-offset: -1px;
}

.field-row {
  display: flex;
  gap: 1rem;
}

.total-row {
  display: flex;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  background: #f8fafc;
  border-radius: 6px;
  color: #0f172a;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 0.5rem;
}

.btn {
  border-radius: 6px;
  padding: 0.625rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid transparent;
}

.btn.primary {
  background: #2563eb;
  color: #fff;
}

.btn.primary:hover:not(:disabled) {
  background: #1d4ed8;
}

.btn.primary:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.btn.secondary {
  background: #fff;
  color: #0f172a;
  border-color: #e2e8f0;
}

.btn.secondary:hover {
  background: #f1f5f9;
}

.error-banner {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
  border-radius: 6px;
  padding: 0.75rem 1rem;
  font-size: 0.875rem;
}

.muted {
  color: #64748b;
}

.details {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem 1.5rem;
  margin: 0;
}

.details .wide {
  grid-column: 1 / -1;
}

.details dt {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 0.25rem;
}

.details dd {
  margin: 0;
  color: #0f172a;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.15s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

@media (max-width: 480px) {
  .field-row,
  .details {
    grid-template-columns: 1fr;
    flex-direction: column;
  }
}
</style>
