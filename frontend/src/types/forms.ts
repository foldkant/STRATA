export type FormFieldOption = {
  label: string
  value: string | number | boolean
}

export type FormField = {
  name: string
  label: string
  type?: 'text' | 'password' | 'select' | 'textarea' | 'checkbox' | 'tel' | 'number'
  required?: boolean
  placeholder?: string
  pattern?: string
  maxlength?: number
  autocomplete?: string
  helper?: string
  options?: FormFieldOption[]
}
