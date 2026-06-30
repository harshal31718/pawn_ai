import { useNavigate } from 'react-router-dom'
import ImageLabPageComponent from '../components/ImageLabPage'

export default function ImageLabPage() {
  const navigate = useNavigate()

  return (
    <ImageLabPageComponent onClose={() => navigate('/chat')} />
  )
}
