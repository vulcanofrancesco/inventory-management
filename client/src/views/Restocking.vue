<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <div class="budget-row">
          <label for="budget-slider" class="budget-label">{{ t('restocking.budget') }}</label>
          <span class="budget-value">{{ formatMoney(budget) }}</span>
        </div>
        <input
          id="budget-slider"
          v-model.number="budget"
          type="range"
          min="0"
          :max="sliderMax"
          step="100"
          class="budget-slider"
        />
        <div class="budget-scale">
          <span>{{ formatMoney(0) }}</span>
          <span>{{ t('restocking.coverAll') }}: {{ formatMoney(maxBudget) }}</span>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.selectedTotal') }}</div>
          <div class="stat-value">{{ formatMoney(totalCost, 2) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remaining') }}</div>
          <div class="stat-value">{{ formatMoney(Math.max(0, budget - totalCost), 2) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.itemsSelected') }}</div>
          <div class="stat-value">{{ items.length }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.maxLeadTime') }}</div>
          <div class="stat-value">{{ t('restocking.days', { count: maxLeadTime }) }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }}</h3>
          <button
            class="place-order-btn"
            :disabled="items.length === 0 || submitting || updating"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="submittedOrder" class="success-banner">
          {{ t('restocking.orderPlaced', { number: submittedOrder.order_number }) }}
          <router-link to="/orders">{{ t('restocking.viewInOrders') }}</router-link>
        </div>

        <div v-if="items.length === 0" class="empty-state">
          {{ t('restocking.noItems') }}
        </div>
        <div v-else class="table-container" :class="{ updating }">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.priority') }}</th>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.item') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th class="num">{{ t('restocking.table.quantity') }}</th>
                <th class="num">{{ t('restocking.table.unitCost') }}</th>
                <th class="num">{{ t('restocking.table.lineTotal') }}</th>
                <th class="num">{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.sku">
                <td>#{{ item.priority_rank }}</td>
                <td><strong>{{ item.sku }}</strong></td>
                <td>{{ item.name }}</td>
                <td>
                  <span :class="['badge', item.trend]">{{ t(`trends.${item.trend}`) }}</span>
                </td>
                <td class="num">{{ item.quantity.toLocaleString() }}</td>
                <td class="num">{{ formatMoney(item.unit_cost, 2) }}</td>
                <td class="num"><strong>{{ formatMoney(item.line_total, 2) }}</strong></td>
                <td class="num">{{ t('restocking.days', { count: item.lead_time_days }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrencyWithDecimals } from '../utils/currency'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency } = useI18n()
    const loading = ref(true)
    const updating = ref(false)
    const submitting = ref(false)
    const error = ref(null)

    const budget = ref(0)
    const maxBudget = ref(0)
    const totalCost = ref(0)
    const items = ref([])
    const submittedOrder = ref(null)

    // Round the slider's upper bound up to the next $100 step so the
    // "cover everything" amount is always reachable.
    const sliderMax = computed(() => Math.ceil(maxBudget.value / 100) * 100)
    const maxLeadTime = computed(() =>
      items.value.reduce((max, item) => Math.max(max, item.lead_time_days), 0)
    )

    const formatMoney = (amount, decimals = 0) =>
      formatCurrencyWithDecimals(amount, currentCurrency.value, decimals)

    const applyRecommendations = (data) => {
      maxBudget.value = data.max_budget
      totalCost.value = data.total_cost
      items.value = data.items
    }

    const loadInitial = async () => {
      try {
        loading.value = true
        error.value = null
        // No budget param: the backend returns the full plan and its cost
        const data = await api.getRestockRecommendations()
        applyRecommendations(data)
        budget.value = Math.ceil(data.max_budget / 100) * 100
      } catch (err) {
        error.value = t('restocking.loadError') + ': ' + err.message
      } finally {
        loading.value = false
      }
    }

    let debounceTimer = null
    let requestId = 0
    const refreshForBudget = async (value) => {
      // Ignore responses from older slider positions that arrive late
      const thisRequest = ++requestId
      try {
        updating.value = true
        const data = await api.getRestockRecommendations(value)
        if (thisRequest === requestId) applyRecommendations(data)
      } catch (err) {
        error.value = t('restocking.loadError') + ': ' + err.message
      } finally {
        if (thisRequest === requestId) updating.value = false
      }
    }

    watch(budget, (value) => {
      if (loading.value) return
      submittedOrder.value = null
      clearTimeout(debounceTimer)
      debounceTimer = setTimeout(() => refreshForBudget(value), 250)
    })

    const placeOrder = async () => {
      if (items.value.length === 0) return
      try {
        submitting.value = true
        submittedOrder.value = await api.submitRestockOrder(
          items.value.map(item => ({ sku: item.sku, quantity: item.quantity }))
        )
      } catch (err) {
        error.value = t('restocking.submitError') + ': ' + err.message
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadInitial)
    onBeforeUnmount(() => clearTimeout(debounceTimer))

    return {
      t,
      loading,
      updating,
      submitting,
      error,
      budget,
      maxBudget,
      sliderMax,
      totalCost,
      items,
      maxLeadTime,
      submittedOrder,
      formatMoney,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-card {
  margin-bottom: 1.5rem;
}

.budget-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 0.75rem;
}

.budget-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.budget-value {
  font-size: 1.75rem;
  font-weight: 700;
  color: #0f172a;
}

.budget-slider {
  width: 100%;
  accent-color: #2563eb;
  cursor: pointer;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  font-size: 0.8125rem;
  color: #64748b;
  margin-top: 0.375rem;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
}

.place-order-btn {
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 0.625rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}

.place-order-btn:hover:not(:disabled) {
  background: #1d4ed8;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.success-banner {
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #065f46;
  border-radius: 6px;
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
  font-size: 0.875rem;
}

.success-banner a {
  color: #047857;
  font-weight: 600;
  margin-left: 0.5rem;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
}

.table-container.updating {
  opacity: 0.6;
  transition: opacity 0.15s;
}

.num {
  text-align: right;
}
</style>
