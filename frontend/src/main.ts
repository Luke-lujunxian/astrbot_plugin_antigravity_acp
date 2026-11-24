import '@fontsource/outfit/400.css';
import '@fontsource/outfit/500.css';
import '@fontsource/outfit/600.css';
import '@fontsource/outfit/700.css';
import 'vuetify/styles';
import './styles/astrbot-theme.css';

import { createApp } from 'vue';
import App from './App.vue';
import vuetify from './plugins/vuetify';

createApp(App).use(vuetify).mount('#app');
