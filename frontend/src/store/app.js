import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', {
  state: () => ({
    // 当前角色：public 群众 / staff 工作人员 / admin 管理员
    role: localStorage.getItem('gov_role') || '',
    username: localStorage.getItem('gov_username') || '',
    // 群众端历史咨询（会话列表）
    chatSessions: JSON.parse(localStorage.getItem('gov_chat_sessions') || '[]')
  }),
  actions: {
    setRole(role) {
      this.role = role
      localStorage.setItem('gov_role', role)
    },
    setUsername(name) {
      this.username = name
      localStorage.setItem('gov_username', name)
    },
    logout() {
      this.role = ''
      this.username = ''
      localStorage.removeItem('gov_role')
      localStorage.removeItem('gov_username')
    },
    addChatSession(session) {
      this.chatSessions.unshift(session)
      this.chatSessions = this.chatSessions.slice(0, 50)
      localStorage.setItem('gov_chat_sessions', JSON.stringify(this.chatSessions))
    },
    upsertSession(id, session) {
      const idx = this.chatSessions.findIndex((s) => s.id === id)
      if (idx > -1) this.chatSessions.splice(idx, 1, session)
      else this.chatSessions.unshift(session)
      this.chatSessions = this.chatSessions.slice(0, 50)
      localStorage.setItem('gov_chat_sessions', JSON.stringify(this.chatSessions))
    }
  }
})
