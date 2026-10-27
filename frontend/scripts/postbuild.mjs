import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { postbuild } from '../src/shared/build/postbuild.mjs'

const frontendDir = join(dirname(fileURLToPath(import.meta.url)), '..')

postbuild({
  app: 'nest_restaurant',
  frontendDir,
  workerTemplate: join(frontendDir, 'src', 'shared', 'sw', 'worker.js'),
  surfaces: [
    {
      entry: 'staff',
      page: 'nest-restaurant',
      route: '/nest-restaurant',
      name: 'Nest Restaurant',
      shortName: 'Nest Restaurant',
      description: 'Restaurant floor, kitchen and till for ERPNext',
      background: '#f4f5f6',
      theme: '#1e1d1d',
      cachePrefix: 'nestrest-staff-',
      exclude: ['/nest-restaurant/customer'],
      shortcuts: [{ name: 'Floor', url: '/nest-restaurant/floor' }, { name: 'Kitchen', url: '/nest-restaurant/kitchen' }],
    },
    {
      entry: 'customer',
      page: 'nest-restaurant-customer',
      route: '/nest-restaurant/customer',
      name: 'Nest Order',
      shortName: 'Nest Order',
      description: 'Order from your table',
      background: '#1e1d1d',
      theme: '#1e1d1d',
      cachePrefix: 'nestrest-guest-',
    },
  ],
})
